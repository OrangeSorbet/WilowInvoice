import subprocess
import sys
from pathlib import Path

def build():
    main_script = "main.py"
    output_dir = Path("dist")

    cmd = [
        sys.executable, "-m", "nuitka",

        # Build mode
        "--standalone",
        "--onefile",

        # Plugins
        "--enable-plugin=pyside6",
        "--spacy-language-model=en_core_web_sm",

        # Data
        "--include-data-dir=config=config",

        # Windows behavior
        "--windows-console-mode=disable",
        "--assume-yes-for-downloads",

        # Output
        f"--output-dir={output_dir}",

        # Metadata (required consistency)
        "--company-name=WilowCorp",
        "--product-name=InvoiceExtractor",
        "--file-version=1.0.0.0",
        "--product-version=1.0.0.0",

        # Entry point
        main_script,
    ]

    print("🚀 Starting Nuitka Build (this may take several minutes on first run)...")
    subprocess.check_call(cmd)
    print(f"✅ Build Complete! Executable available in: {output_dir.resolve()}")

if __name__ == "__main__":
    build()
