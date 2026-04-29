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


def download_voice(key: str, info: dict) -> None:
    print("\n" + "=" * 70)
    print(f"Voix: {info['label']}")
    print("=" * 70)

    model_path = Path(info["model"])
    config_path = Path(info["config"])

    if not model_path.exists():
        download_file(info["model_url"], model_path)
    else:
        print(f"Modèle déjà installé: {model_path}")

    if not config_path.exists():
        download_file(info["config_url"], config_path)
    else:
        print(f"Config déjà installée: {config_path}")

    if model_path.exists() and config_path.exists():
        print(f"OK: {model_path.name}")
    else:
        print("ATTENTION: voix incomplète.")


def main() -> None:
    PIPER_VOICES_DIR.mkdir(parents=True, exist_ok=True)
    print("Téléchargement automatique des voix Piper FR + AR...")
    print(f"Dossier voix Piper: {PIPER_VOICES_DIR}")

    # Évite de télécharger deux fois la même voix ar/ar_linto.
    seen_models = set()
    for key, info in PIPER_VOICES.items():
        model_path = str(info["model"])
        if model_path in seen_models:
            continue
        seen_models.add(model_path)
        try:
            download_voice(key, info)
        except Exception as error:
            print("\nERREUR pendant le téléchargement de la voix Piper.")
            print(f"Voix: {info['label']}")
            print(f"Détail: {error}")

    print("\nTerminé.")
    print("Si Piper n'est pas installé, lance: pip install -r requirements.txt")


if __name__ == "__main__":
    main()
