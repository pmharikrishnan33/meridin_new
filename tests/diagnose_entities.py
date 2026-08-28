import asyncio

from app.ml.entity_extractor import entity_extractor


async def main() -> None:
    text = "I need a black shirt"

    result = await entity_extractor.extract_async(
        text
    )

    print("=" * 60)
    print("ENTITY DIAGNOSTIC")
    print("=" * 60)

    print()
    print("MESSAGE:")
    print(text)

    print()
    print("EXTRACTED DICT:")
    print(result.extracted_dict)

    print()
    print("ENTITIES:")

    for entity in result.entities:
        print(
            f"{entity.entity_type.value:15} "
            f"value={entity.value!r:15} "
            f"normalized={entity.normalized_value!r:15} "
            f"confidence={entity.confidence:.3f}"
        )


if __name__ == "__main__":
    asyncio.run(main())