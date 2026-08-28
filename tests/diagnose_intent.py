import joblib
from pathlib import Path


# ---------------------------------------------------------
# Locate model files
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MODEL_PATH = PROJECT_ROOT/"models" / "intent_model.pkl"
VECTORIZER_PATH = PROJECT_ROOT/"models" / "intent_vectorizer.pkl"


print("=" * 60)
print("MERIDIN INTENT MODEL DIAGNOSTIC")
print("=" * 60)

print(f"\nModel path:")
print(MODEL_PATH)

print(f"\nVectorizer path:")
print(VECTORIZER_PATH)


# ---------------------------------------------------------
# Check files
# ---------------------------------------------------------

if not MODEL_PATH.exists():
    print("\nERROR: intent_model.pkl not found")
    raise SystemExit(1)

if not VECTORIZER_PATH.exists():
    print("\nERROR: tfidf_vectorizer.pkl not found")
    raise SystemExit(1)


# ---------------------------------------------------------
# Load artifacts
# ---------------------------------------------------------

try:
    model = joblib.load(MODEL_PATH)
    vectorizer = joblib.load(VECTORIZER_PATH)

except Exception as exc:
    print("\nERROR while loading model/vectorizer:")
    print(repr(exc))
    raise SystemExit(1)


# ---------------------------------------------------------
# Basic model information
# ---------------------------------------------------------

print("\n" + "=" * 60)
print("MODEL INFORMATION")
print("=" * 60)

print("\nModel type:")
print(type(model))

print("\nVectorizer type:")
print(type(vectorizer))

print("\nModel classes:")
print(model.classes_)

print("\nNumber of classes:")
print(len(model.classes_))


# ---------------------------------------------------------
# Vectorizer information
# ---------------------------------------------------------

print("\n" + "=" * 60)
print("VECTORIZER INFORMATION")
print("=" * 60)

try:
    print("\nVocabulary size:")
    print(len(vectorizer.vocabulary_))

except Exception:
    print("\nCould not read vocabulary size.")


# ---------------------------------------------------------
# Test messages
# ---------------------------------------------------------

test_messages = [
    "hello",
    "hi",
    "good morning",
    "I need a black shirt",
    "show me black shirts",
    "I want to buy a shirt",
    "where is my order",
    "I want to return my order",
]


print("\n" + "=" * 60)
print("PREDICTION RESULTS")
print("=" * 60)


for text in test_messages:

    print("\n" + "-" * 60)
    print("MESSAGE:")
    print(text)

    try:
        X = vectorizer.transform([text])

        probabilities = model.predict_proba(X)[0]

        results = sorted(
            zip(
                model.classes_,
                probabilities,
            ),
            key=lambda item: item[1],
            reverse=True,
        )

        print("\nTop predictions:")

        for intent, probability in results:
            print(
                f"{str(intent):20} "
                f"{float(probability):.6f}"
            )

        best_intent, best_probability = results[0]

        print("\nBEST INTENT:")
        print(best_intent)

        print("\nBEST CONFIDENCE:")
        print(
            f"{float(best_probability):.6f}"
        )

        if len(results) > 1:

            second_intent, second_probability = results[1]

            margin = (
                float(best_probability)
                - float(second_probability)
            )

            print("\nSECOND INTENT:")
            print(second_intent)

            print("\nSECOND CONFIDENCE:")
            print(
                f"{float(second_probability):.6f}"
            )

            print("\nCONFIDENCE MARGIN:")
            print(
                f"{margin:.6f}"
            )

    except Exception as exc:

        print("\nERROR while predicting:")
        print(repr(exc))


print("\n" + "=" * 60)
print("DIAGNOSTIC COMPLETE")
print("=" * 60)