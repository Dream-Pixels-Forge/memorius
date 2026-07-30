"""Quick-start example: store, search, and retrieve memories."""

import tempfile
from pathlib import Path
from memorius.config import load_config
from memorius.vault import VaultEngine


def main():
    # Use a temporary directory so this doesn't affect your real vault
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir) / "data"
        config_data = load_config()
        config_data["storage"]["path"] = str(storage_path)
        engine = VaultEngine(config_data)

        # 1. Store a memory with full hierarchy
        mem = engine.store(
            content="The Eiffel Tower was built in 1889 for the World's Fair.",
            vault="knowledge",
            shelf="history",
            folder="landmarks",
            note="eiffel-tower",
        )
        print(f"Stored: {mem.id}")

        # 2. Search by semantics
        results = engine.search("When was the Eiffel Tower built?")
        for r in results:
            print(f"  {r.content[:80]}")

        # 3. Mine a conversation transcript
        transcript = (
            "User: What year was the Berlin Wall built?\n"
            "Assistant: The Berlin Wall was built in 1961.\n"
        )
        mined = engine.mine(text=transcript)
        print(f"Mined {len(mined)} memories")
        for m in mined:
            print(f"  [{m.vault}/{m.shelf}] {m.content[:60]}")

        # 4. Write a diary entry
        entry = engine.write_diary(
            session_id="example-session",
            title="Learning about landmarks",
            summary="Explored world landmarks and their construction dates.",
        )
        print(f"Diary entry: {entry['id']}")

        # 5. Show vault status
        status = engine.status()
        print("\nVault status:")
        print(f"  Vaults:              {status['vaults']}")
        print(f"  Memories:            {status['memories']}")
        print(f"  Embedding provider:  {status['embedding_provider']}")
        print(f"  Embedding dimension: {status['embedding_dimension']}")


if __name__ == "__main__":
    main()
