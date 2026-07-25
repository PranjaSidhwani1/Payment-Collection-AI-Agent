"""Interactive CLI for manually chatting with the payment collection agent.

Usage:
    python cli.py
"""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass  # older Python without reconfigure(); currency symbol may not render on some terminals

from dotenv import load_dotenv

load_dotenv()

from agent import Agent  # noqa: E402  (import after load_dotenv on purpose)


def main():
    agent = Agent()
    print("Payment Collection Agent - type 'quit' to exit.\n")
    turn = agent.next("Hi")
    print(f"Agent: {turn['message']}\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user_input.lower() in {"quit", "exit"}:
            break
        if not user_input:
            continue
        turn = agent.next(user_input)
        print(f"Agent: {turn['message']}\n")


if __name__ == "__main__":
    main()
