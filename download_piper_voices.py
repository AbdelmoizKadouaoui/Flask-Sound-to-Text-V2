from pathlib import Path
import urllib.request

from config import PIPER_VOICES, PIPER_VOICES_DIR


def download_file(url: str, destination: Path) -> None:
    print(f"Téléchargement depuis: {url}")
    print(f"Vers: {destination}")

    def progress(block_num, block_size, total_size):
        if total_size <= 0:
            return
        downloaded = block_num * block_size
        percent = min(downloaded * 100 / total_size, 100)
        print(f"\rTéléchargement: {percent:.1f}%", end="")

    urllib.request.urlretrieve(url, destination, progress)
    print("\nTéléchargement terminé.")


def main() -> None:
    PIPER_VOICES_DIR.mkdir(parents=True, exist_ok=True)

    print("Téléchargement automatique des voix Piper FR + AR...")
    print(f"Dossier voix Piper: {PIPER_VOICES_DIR}")

    for lang, info in PIPER_VOICES.items():
        print("\n" + "=" * 70)
        print(f"Voix: {info['label']}")
        print("=" * 70)

        model_path = PIPER_VOICES_DIR / info["model"]
        config_path = PIPER_VOICES_DIR / info["config"]

        if not model_path.exists():
            download_file(info["model_url"], model_path)
        else:
            print(f"Modèle déjà présent: {model_path.name}")

        if not config_path.exists():
            download_file(info["config_url"], config_path)
        else:
            print(f"Config déjà présente: {config_path.name}")

        if model_path.exists() and config_path.exists():
            print(f"OK: {model_path.name}")
        else:
            print("ATTENTION: voix incomplète.")

    print("\nTerminé.")
    print("Si Piper n'est pas installé, lance: pip install -r requirements.txt")


if __name__ == "__main__":
    main()
