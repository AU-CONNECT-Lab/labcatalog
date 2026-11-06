import re

# A whole answer wrapped in one markdown code fence, as models often send code.
FENCED = re.compile(r"^\s*```[^\n]*\n(.*?)\n?```\s*$", re.DOTALL)


def unfenced(text: str) -> str:
    found = FENCED.match(text)
    return found.group(1) if found else text
