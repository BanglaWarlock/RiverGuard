import os

# Root directory to scan
root_dir = "."

# Folders and file extensions/names to exclude
exclude_dirs = {"__pycache__", "web", "log", "data"}
exclude_files = {"style.css",}  # Add files you want to skip reading/showing
excluded_extensions = {}  # Extensions to not read content from

for current_root, dirs, files in os.walk(root_dir):
  # Modify dirs in-place to skip excluded directories
  dirs[:] = [d for d in dirs if d not in exclude_dirs]

  for file in files:
    if file in exclude_files:
      continue

    file_path = os.path.join(current_root, file)
    ext = os.path.splitext(file)[1].lower()

    print(f"\n--- FILE: {file_path} ---")

    if ext not in excluded_extensions:
      try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
          content = f.read()
          print(content)
      except Exception as e:
        print(f"[Could not read file: {e}]")
