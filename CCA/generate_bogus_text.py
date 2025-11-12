import argparse
import lorem

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tool to generate the given amount of data")
    parser.add_argument("size", type=int, help="How many bytes (approximately) should we generate?")
    args = parser.parse_args()
    print(args.size, type(args.size))
    
    generated = 0
    while generated < args.size:
        para = lorem.paragraph() + "\n"
        generated += len(para)
        print(para)
