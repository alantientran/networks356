# standard library imports
import argparse
import math
import random
import sys
import scipy.sparse

# import assignment-3-specific files
from graph import gen_rand_graph, graph_from_file, Graph
from dv_router import DVRouter
from ls_router import LSRouter
import random

# Maximum link cost for randomly generated topologies
MAX_LINK_COST = 10000
NUM_TICKS = 10000


# Exception class for unimplemented code
class UnimplementedCode(Exception):
    pass

class Clock:
    def __init__(self):
        self.__current_tick = -math.inf

    def set_tick(self, tick):
        assert tick > self.__current_tick
        self.__current_tick = tick

    def read_tick(self):
        return self.__current_tick

# compute shortest path from predecessor array (preds)
def compute_shortest_path(src, dst, preds):
    # -9999 is a special value that scipy uses if no path exists between src and dst
    # This could happen if either src == dst,
    # or if src is disconnected from destination. We'll assert both false.
    assert preds[src][dst] != -9999
    assert src != dst

    if preds[src][dst] == src:
        return []  # base case, src and dst are directly connected
    else:
        return compute_shortest_path(src, preds[src][dst], preds) + [preds[src][dst]]


# check routing algorithm is either DV or LS
def check_algo_type(algo_type):
    if algo_type not in ["DV", "LS"]:
        raise argparse.ArgumentTypeError(
            "Invalid routing algorithm type, must be DV or LS."
        )
    return algo_type


# check link prob is between 0.0 and 1.0
def check_link_prob(link_prob_str):
    link_prob = float(link_prob_str)
    if (link_prob > 1.0) or (link_prob < 0.0):
        raise argparse.ArgumentTypeError("Link probability must be between 0 and 1.")
    return link_prob


def check_graphs(num_nodes, offline_sp, rt_algo_sp, distances, adj_mat):
    for i in range(0, num_nodes):
        for j in range(0, num_nodes):
            if i != j:
                if offline_sp[i][j] != rt_algo_sp[i][j]:
                    print(
                        "\nNOTE: Routing algorithm computed shortest path from ",
                        i,
                        " to ",
                        j,
                        " as ",
                        rt_algo_sp[i][j],
                        "\nOffline algorithm computed shortest path from ",
                        i,
                        " to ",
                        j,
                        " as ",
                        offline_sp[i][j],
                    )
                    rt_distance = 0
                    for index in range(1, len(rt_algo_sp[i][j])):
                        rt_distance += adj_mat[rt_algo_sp[i][j][index - 1]][
                            rt_algo_sp[i][j][index]
                        ]
                    print(
                        "Distance computed by offline algorithm = ",
                        distances[i][j],
                        "\nDistance computed by routing algorithm = ",
                        rt_distance,
                    )
                    if rt_distance == distances[i][j]:
                        print(
                            "Distances computed by both algorithms are the same even though paths are different"
                        )
                    else:
                        print("ERROR!!!: Distances differ")
                        return False
    return True


def compute_route(num_nodes, routers):
    # Routing algorithm (DV/LS)'s shortest paths
    rt_algo_sp = [[0 for x in range(num_nodes)] for y in range(num_nodes)]
    for i in range(0, num_nodes):
        for j in range(0, num_nodes):
            if i != j:
                if j not in routers[i].fwd_table:
                    raise UnimplementedCode(
                        str(j) + " isn't in router " + str(i) + "'s fwd table"
                    )
                next_hop = routers[i].fwd_table[j]
                router_path = []
                while next_hop != j:
                    router_path += [next_hop]
                    if j not in routers[next_hop].fwd_table:
                        raise UnimplementedCode(
                            str(j)
                            + " isn't in router "
                            + str(next_hop)
                            + "'s fwd table"
                        )
                    next_hop = routers[next_hop].fwd_table[j]
                rt_algo_sp[i][j] = [i] + router_path + [j]
    return rt_algo_sp


def get_routers(rt_algo, num_nodes, test_graph, clock):
    routers = []
    for i in range(0, num_nodes):
        if rt_algo == "DV":
            routers.append(DVRouter(i, clock))
        elif rt_algo == "LS":
            routers.append(LSRouter(i, clock))
        else:
            assert False

    # Populate router's neighbors and links based on the random graph
    for i in range(0, num_nodes):
        # Add neighbors first
        adj_list = test_graph.adj_list[i]
        neighbors_as_refs = [routers[elem[0]] for elem in adj_list]
        routers[i].add_neighbors(neighbors_as_refs)

        # Add links next
        links = dict()
        for elem in adj_list:
            links[elem[0]] = elem[1]
        routers[i].add_links(links)

        # Init either DV/LS algorithm
        routers[i].initialize_algorithm()
    return routers


class Simulator:
    def __init__(self, seed, rt_algo, test_graph, clock, check_convergence=False):
        self.seed = seed
        self.test_graph = test_graph
        self.rt_algo = rt_algo
        self.clock = clock
        self.check_convergence = check_convergence

    def run(self):
        adj_mat = self.test_graph.adj_mat()

        # Ensure that it is connected
        num_components = scipy.sparse.csgraph.connected_components(
            adj_mat, return_labels=False
        )

        if num_components != 1:
            raise argparse.ArgumentTypeError(
                "Input graph is disconnected.\nFor randomly generated graphs,"
                " use a different seed or increase the link probability."
                "\nFor graphs generated from files, check the graph file."
            )

        # Create LS or DV routers
        num_nodes = len(self.test_graph.adj_list)
        routers = get_routers(self.rt_algo, num_nodes, self.test_graph, self.clock)

        # Now simulate, checking for convergence if the flag is set.
        if self.check_convergence:
            if self.rt_algo == "DV": 
                for tick in range(0, NUM_TICKS):
                    self.clock.set_tick(tick)
                    updated = False
                    for i in range(0, num_nodes):
                        updated |= routers[i].run_one_tick_check_convergence()
                    if not updated:
                        print(f"Converged at tick {tick}")
                        break
            else: # self.rt_algo == "LS"
                for tick in range(0, NUM_TICKS):
                    self.clock.set_tick(tick)
                    updated = False
                    for i in range(0, num_nodes):
                        updated |= routers[i].run_one_tick_check_convergence()
                    if not updated:
                        print(f"Converged at tick {tick}")
                        for i in range(0, num_nodes):
                            routers[i].broadcast_complete = True
                            routers[i].dijkstras_algorithm()
                            routers[i].routes_computed = True
                        break
        else:
            # Not checking for convergence.
            for tick in range(0, NUM_TICKS):
                self.clock.set_tick(tick)
                for i in range(0, num_nodes):
                    routers[i].run_one_tick()            

        # Offline computation of the graph's shortest paths
        (distances, preds) = scipy.sparse.csgraph.shortest_path(
            adj_mat, return_predecessors=True
        )

        # Walk through preds to determine shortest paths
        offline_sp = [[0 for x in range(num_nodes)] for y in range(num_nodes)]
        for i in range(0, num_nodes):
            for j in range(0, num_nodes):
                if i != j:
                    offline_sp[i][j] = [i] + compute_shortest_path(i, j, preds) + [j]
        rt_algo_sp = compute_route(num_nodes, routers)

        # Compare the two and return the result
        return check_graphs(num_nodes, offline_sp, rt_algo_sp, distances, adj_mat)

    def run_with_failure(self):
        # Inject a failure at a fixed tick
        # It doesn't compare the routing algorithm to the offline algorithms.
        #   and always returns True - ignore the return value.
        
        num_nodes = len(self.test_graph.adj_list)
        
        # Failure node is fixed to be the last node
        failure_node = num_nodes - 1
        
        # Create LS or DV routers
        routers = get_routers(self.rt_algo, num_nodes, self.test_graph, self.clock)
        FAILURE_TICK = 100

        for tick in range(0, NUM_TICKS):
            self.clock.set_tick(tick)
            for i in range(0, num_nodes):
                if tick > FAILURE_TICK:
                    if i != failure_node:
                        routers[i].run_one_tick()
                else:
                    routers[i].run_one_tick()
                          
            if tick == FAILURE_TICK:
                print(f"Node {failure_node} fails at tick {tick}")
                # Remove all links to/from failure_node
                for neighbor in routers[failure_node].neighbors:
                    if failure_node in neighbor.links:
                        del neighbor.links[failure_node]
                    if failure_node in neighbor.fwd_table:
                        del neighbor.fwd_table[failure_node]
                    if self.rt_algo == "DV":
                        if failure_node in neighbor.dv:
                            del neighbor.dv[failure_node]
                    neighbor.neighbors = [nbr for nbr in neighbor.neighbors if nbr.router_id != failure_node]

                for i in range(num_nodes):
                    if i != failure_node and self.rt_algo == "DV":
                        routers[i].dv_change = True  # Trigger DV update due to link failure

                # Clear links and fwd_table of failed node
                routers[failure_node].links = dict()
                routers[failure_node].fwd_table = dict()
                if self.rt_algo == "DV":
                    routers[failure_node].dv = dict()
                elif self.rt_algo == "LS":
                    routers[failure_node].lsa_dict = dict()
                    routers[failure_node].broadcasted = dict()

        # Print out the final forwarding tables and routing info
        for i in range(num_nodes):
            print(f"Router {i} forwarding table: {routers[i].fwd_table}")
            if self.rt_algo == "DV":
                print(f"Router {i} distance vector: {routers[i].dv}")
            elif self.rt_algo == "LS":
                print(f"Router {i} link state: {routers[i].lsa_dict}")
        
        # Ignore the return value.
        return True

def run_rand_test(seed, num_routers, link_prob, rt_algo, clock, check_convergence):
    # Seed random number generator
    random.seed(seed)
    # Create test_graph
    test_graph = gen_rand_graph(num_routers, link_prob, MAX_LINK_COST)
    # create the simulator
    sim = Simulator(seed, rt_algo, test_graph, clock, check_convergence)
    return sim.run()

def run_file_test(graph_file, rt_algo, clock, check_convergence):
    # Create test_graph
    test_graph = graph_from_file(graph_file)
    # create the simulator
    sim = Simulator(0, rt_algo, test_graph, clock, check_convergence)
    return sim.run()

def run_link_failure_test(graph_file, rt_algo, clock):
    # Create test_graph
    test_graph = graph_from_file(graph_file)    
    # create the simulator
    sim = Simulator(0, rt_algo, test_graph, clock, False)
    return sim.run_with_failure()

def main(args):
    clock = Clock()
    
    if args.input_type == "rand_input":
        success = run_rand_test(
            args.seed,
            args.num_routers,
            args.link_prob,
            args.rt_algo,
            clock,
            args.check_convergence,
        )
    elif args.input_type == "file_input":
        if args.inject_failure:
            success = run_link_failure_test(
                args.graph_file,
                args.rt_algo,
                clock,
            )
        else:
            success = run_file_test(
                args.graph_file,
                args.rt_algo,
                clock,
                args.check_convergence,
            )
    else:
        raise argparse.ArgumentTypeError("Must specify one of rand_input or file_input")

    if not success:
        print(
            "\nERROR: There was at least one path on which"
            " routing and offline algorithm did not agree"
        )
        sys.exit(1)
    print(
        "\nSUCCESS: Routing and offline algorithm agree on "
        "shortest paths between all node pairs"
    )
    sys.exit(0)


if __name__ == "__main__":
    # Usage for command line arguments
    parser = argparse.ArgumentParser(description="Assignment 3 simulator.")
    parser.add_argument(
        "rt_algo",
        type=check_algo_type,
        help="Type of routing algorithm. Must be either DV or LS",
    )

    subparsers = parser.add_subparsers(
        dest="input_type",
        help="Type of graph input. Must be either file_input or rand_input",
        metavar="input_type",
    )
    subparsers.required = True

    # Add a subparser for randomly generated test graphs
    # and another one for test graphs specified as files
    rand_input_parser = subparsers.add_parser(
        "rand_input", help="Generate random graph as test input"
    )
    file_input_parser = subparsers.add_parser(
        "file_input", help="Use user-specified file as test input"
    )

    # Rand input arguments
    rand_input_parser.add_argument(
        "--seed",
        dest="seed",
        type=int,
        help="Seed for generating random graphs",
        required=True,
    )
    rand_input_parser.add_argument(
        "--num_routers",
        dest="num_routers",
        type=int,
        help="Number of routers in topology",
        required=True,
    )
    rand_input_parser.add_argument(
        "--link_prob",
        dest="link_prob",
        type=check_link_prob,
        help="Probability of a link between two routers, "
        "used for generating random router topologies",
        required=True,
    )

    # File input arguments
    file_input_parser.add_argument(
        "--graph_file",
        dest="graph_file",
        type=str,
        help="Graph file to be used for testing routing protocol",
        required=True,
    )
    
    # Convergence check args
    parser.add_argument(
        "--check_convergence",
        dest="check_convergence",
        action="store_true",
        help="Whether to log the elapsed ticks to convergence",
        default=False,
    )

    # Inject failure test
    parser.add_argument(
        "--inject_failure",
        dest="inject_failure",
        action="store_true",
        help="Whether to run simulation with a 3-node line topology and a link failure",
        default=False,
    )

    # Actually carry out parsing
    arguments = parser.parse_args()
    for arg in vars(arguments):
        print("%s: %s" % (arg, getattr(arguments, arg)))

    main(arguments)
