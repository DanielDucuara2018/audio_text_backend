import random
import string

def generate_random_name(prefix: str) -> str:  # fix calculation
    return f"{prefix}_{''.join(random.choices(string.ascii_lowercase, k = 16))}"