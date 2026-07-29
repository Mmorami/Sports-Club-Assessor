import ast
import os
from pathlib import Path


def parse_python_file(file_path: Path) -> str:
    """Parses a Python file using AST and extracts module, class, and function definitions."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            node = ast.parse(f.read(), filename=str(file_path))
    except Exception as e:
        return f"  - Error parsing file: {e}\n"

    output = []
    
    # Extract module docstring if present
    docstring = ast.get_docstring(node)
    if docstring:
        first_line = docstring.strip().split("\n")[0]
        output.append(f"  > *{first_line}*\n")

    for item in node.body:
        # Top-level functions
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in item.args.args]
            output.append(f"  - `def {item.name}({', '.join(args)})`\n")

        # Classes and their methods
        elif isinstance(item, ast.ClassDef):
            output.append(f"  - `class {item.name}`\n")
            for sub_item in item.body:
                if isinstance(sub_item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = [a.arg for a in sub_item.args.args]
                    output.append(f"    - `def {sub_item.name}({', '.join(args)})`\n")

    return "".join(output) if output else "  - *No classes or top-level functions defined.*\n"


def generate_codebase_map(src_dir: str = "src", output_file: str = "docs/CODEBASE_MAP.md"):
    """Scans the src directory and writes an AST-based codebase map to markdown."""
    src_path = Path(src_dir)
    out_path = Path(output_file)

    if not src_path.exists():
        print(f"Directory '{src_dir}' does not exist.")
        return

    # Ensure output directory exists
    out_path.parent.mkdir(parents=True, exist_ok=True)

    markdown_content = [
        "# Codebase Map (AST Index)\n",
        "> **Note for AI Agents:** Do NOT run `grep` or `glob` across the codebase.",
        "> Consult this file first to identify relevant paths, classes, and method signatures.\n",
        f"**Source Directory:** `{src_dir}/`  \n\n",
        "---",
        "\n"
    ]

    # Walk through all python files in src/
    python_files = sorted(list(src_path.rglob("*.py")))

    if not python_files:
        markdown_content.append("*No Python files found in source directory.*\n")
    else:
        for py_file in python_files:
            rel_path = py_file.relative_to(src_path.parent)
            markdown_content.append(f"### `{rel_path}`\n")
            markdown_content.append(parse_python_file(py_file))
            markdown_content.append("\n")

    with open(out_path, "w", encoding="utf-8") as f:
        f.writelines(markdown_content)

    print(f"Codebase map successfully generated at: {out_path}")


if __name__ == "__main__":
    generate_codebase_map()
