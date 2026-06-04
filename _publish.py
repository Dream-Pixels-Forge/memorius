import subprocess, sys
result = subprocess.run(
    [sys.executable, "-m", "twine", "upload", "--verbose", "dist/*",
     "--username", "__token__",
     "--password", "pypi-A...JkIg"],
    capture_output=True, text=True, timeout=120
)
print("RC:", result.returncode)
print("=== STDOUT ===")
print(result.stdout[-1500:])
print("=== STDERR ===")
print(result.stderr[-1500:])
