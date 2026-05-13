import argostranslate.package
import sys

def main():
    print("Updating package index...")
    argostranslate.package.update_package_index()
    available_packages = argostranslate.package.get_available_packages()
    
    zh_to_en = next(
        filter(
            lambda x: x.from_code == "zh" and x.to_code == "en", available_packages
        ), None
    )
    
    if not zh_to_en:
        print("Error: Chinese to English package not found.")
        sys.exit(1)
        
    print(f"Installing ZH -> EN model...")
    argostranslate.package.install_from_path(zh_to_en.download())
    print("Translation model installed successfully.")

if __name__ == "__main__":
    main()
