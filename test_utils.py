import json
from vault import Vault

# Test vault address
TEST_VAULT = "0xaF5372792a29dC6b296d6FFD4AA3386aff8f9BB2"

def main():
    print(f"Testing with vault address: {TEST_VAULT}")
    try:
        vault = Vault(TEST_VAULT)
        print(json.dumps(vault.to_dict(), indent=2))
    except Exception as e:
        print(f"Test failed: {e}")

if __name__ == "__main__":
    main()
