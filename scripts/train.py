"""
Training pipeline for Meridin's ML models.

Trains two models from the JSON data files in ``data/``:

1. **Intent classifier** — TF-IDF vectorizer + LogisticRegression.
   Input: raw user message text.
   Output: one of the intent class labels.

2. **Entity extractor** — token-level TF-IDF vectorizer + LogisticRegression
   with BIO (Begin / Inside / Outside) tagging.
   Input: individual tokens.
   Output: a BIO tag such as ``B-PRODUCT``, ``I-COLOR``, or ``O``.

Both models are evaluated on a held-out split and persisted as ``.pkl``
files in ``models/`` so they can be loaded by ``app/ml/loader.py`` at
runtime.

Usage::

    .venv/bin/python scripts/train.py
    .venv/bin/python scripts/train.py --intent-only
    .venv/bin/python scripts/train.py --entity-only
    .venv/bin/python scripts/train.py --eval-only
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MODELS_DIR = ROOT / "models"

INTENT_DATA_FILE = DATA_DIR / "intent_training_data.json"
ENTITY_DATA_FILE = DATA_DIR / "entity_training_data.json"

INTENT_MODEL_OUT = MODELS_DIR / "intent_model.pkl"
INTENT_VECTORIZER_OUT = MODELS_DIR / "intent_vectorizer.pkl"
ENTITY_MODEL_OUT = MODELS_DIR / "entity_model.pkl"
ENTITY_VECTORIZER_OUT = MODELS_DIR / "entity_vectorizer.pkl"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("train")

# ---------------------------------------------------------------------------
# Intent training
# ---------------------------------------------------------------------------

# The model may produce class labels that differ from IntentType enum values.
# This alias map normalises them so the classifier always emits canonical
# intent names.  ``cancel_request`` and ``product_availability`` are kept as
# separate classes for richer training signal, then mapped at inference time.
INTENT_ALIASES = {
    "cancel_request": "cancel_order",
    "product_availability": "availability",
}


def load_intent_data() -> Tuple[List[str], List[str]]:
    """Load and flatten intent training data into (texts, labels)."""

    with open(INTENT_DATA_FILE, encoding="utf-8") as fh:
        data: Dict[str, List[str]] = json.load(fh)

    texts: List[str] = []
    labels: List[str] = []

    for intent_label, samples in data.items():
        # Keep the raw label (including aliases) so the model learns the
        # distinction; _map_to_intent_type handles normalisation at inference.
        for sample in samples:
            texts.append(sample.lower().strip())
            labels.append(intent_label)

    log.info(f"Loaded {len(texts)} intent samples across {len(data)} intents")
    for intent, count in sorted(data.items()):
        log.info(f"  {intent}: {count} samples")

    return texts, labels


def train_intent_classifier(
    texts: List[str],
    labels: List[str],
    test_size: float = 0.2,
    random_state: int = 42,
) -> Tuple[LogisticRegression, TfidfVectorizer, dict]:
    """Train a TF-IDF + LogisticRegression intent classifier.

    Returns ``(model, vectorizer, eval_metrics)``.
    """

    log.info("Vectorizing intent training data...")
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        sublinear_tf=True,
        min_df=1,
        max_features=3000,
    )
    X = vectorizer.fit_transform(texts)
    y = np.array(labels)

    log.info(f"Feature matrix shape: {X.shape}")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=y
    )

    log.info(f"Training set: {len(y_train)} samples, Test set: {len(y_test)} samples")

    model = LogisticRegression(
        max_iter=1000,
        class_weight="balanced",
        random_state=random_state,
        solver="lbfgs",
    )
    model.fit(X_train, y_train)

    # Evaluate
    y_pred = model.predict(X_test)
    report = classification_report(y_test, y_pred, output_dict=True, zero_division=0)
    cm = confusion_matrix(y_test, y_pred, labels=sorted(set(labels)))

    log.info("\nIntent classification report:")
    log.info(classification_report(y_test, y_pred, zero_division=0))

    metrics = {
        "classification_report": report,
        "confusion_matrix": cm.tolist(),
        "labels": sorted(set(labels)),
        "n_features": X.shape[1],
        "n_train": len(y_train),
        "n_test": len(y_test),
    }

    return model, vectorizer, metrics


# ---------------------------------------------------------------------------
# Entity training
# ---------------------------------------------------------------------------

def load_entity_data() -> Tuple[List[str], List[str]]:
    """Load entity training data and flatten into (tokens, tags).

    Each training sample is a list of tokens and a parallel list of BIO tags.
    We flatten so that each token becomes one training example.
    """

    with open(ENTITY_DATA_FILE, encoding="utf-8") as fh:
        data = json.load(fh)

    tokens: List[str] = []
    tags: List[str] = []

    for sample in data["samples"]:
        sample_tokens = sample["tokens"]
        sample_tags = sample["tags"]
        if len(sample_tokens) != len(sample_tags):
            log.warning(
                f"Skipping sample with mismatched lengths: "
                f"{len(sample_tokens)} tokens vs {len(sample_tags)} tags"
            )
            continue
        for tok, tag in zip(sample_tokens, sample_tags):
            tokens.append(tok.lower())
            tags.append(tag)

    log.info(f"Loaded {len(tokens)} entity tokens across {len(data['samples'])} samples")

    # Report tag distribution
    from collections import Counter
    tag_counts = Counter(tags)
    for tag, count in sorted(tag_counts.items()):
        log.info(f"  {tag}: {count}")

    return tokens, tags


def train_entity_extractor(
    tokens: List[str],
    tags: List[str],
    test_size: float = 0.2,
    random_state: int = 42,
) -> Tuple[LogisticRegression, TfidfVectorizer, dict]:
    """Train a token-level TF-IDF + LogisticRegression entity extractor.

    Returns ``(model, vectorizer, eval_metrics)``.
    """

    log.info("Vectorizing entity training data...")
    vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 4),
        sublinear_tf=True,
        min_df=1,
        max_features=2000,
    )
    X = vectorizer.fit_transform(tokens)
    y = np.array(tags)

    log.info(f"Feature matrix shape: {X.shape}")

    # Use non-stratified split because many entity tags have very few samples
    # (some I- tags appear only once), making stratification impossible.
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state
    )

    log.info(f"Training set: {len(y_train)} tokens, Test set: {len(y_test)} tokens")

    model = LogisticRegression(
        max_iter=1000,
        class_weight="balanced",
        random_state=random_state,
        solver="lbfgs",
    )
    model.fit(X_train, y_train)

    # Evaluate
    y_pred = model.predict(X_test)
    report = classification_report(y_test, y_pred, output_dict=True, zero_division=0)
    cm = confusion_matrix(y_test, y_pred, labels=sorted(set(tags)))

    log.info("\nEntity extraction report:")
    log.info(classification_report(y_test, y_pred, zero_division=0))

    metrics = {
        "classification_report": report,
        "confusion_matrix": cm.tolist(),
        "labels": sorted(set(tags)),
        "n_features": X.shape[1],
        "n_train": len(y_train),
        "n_test": len(y_test),
    }

    return model, vectorizer, metrics


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------

def save_models(
    intent_model: LogisticRegression | None,
    intent_vectorizer: TfidfVectorizer | None,
    entity_model: LogisticRegression | None,
    entity_vectorizer: TfidfVectorizer | None,
) -> None:
    """Persist trained models to the models/ directory."""

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    if intent_model is not None:
        joblib.dump(intent_model, INTENT_MODEL_OUT)
        log.info(f"Saved intent model → {INTENT_MODEL_OUT}")

    if intent_vectorizer is not None:
        joblib.dump(intent_vectorizer, INTENT_VECTORIZER_OUT)
        log.info(f"Saved intent vectorizer → {INTENT_VECTORIZER_OUT}")

    if entity_model is not None:
        joblib.dump(entity_model, ENTITY_MODEL_OUT)
        log.info(f"Saved entity model → {ENTITY_MODEL_OUT}")

    if entity_vectorizer is not None:
        joblib.dump(entity_vectorizer, ENTITY_VECTORIZER_OUT)
        log.info(f"Saved entity vectorizer → {ENTITY_VECTORIZER_OUT}")


def load_models() -> Tuple[LogisticRegression, TfidfVectorizer, LogisticRegression, TfidfVectorizer]:
    """Load existing models for evaluation."""

    intent_model = joblib.load(INTENT_MODEL_OUT)
    intent_vectorizer = joblib.load(INTENT_VECTORIZER_OUT)
    entity_model = joblib.load(ENTITY_MODEL_OUT)
    entity_vectorizer = joblib.load(ENTITY_VECTORIZER_OUT)

    return intent_model, intent_vectorizer, entity_model, entity_vectorizer


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate_intent(
    model: LogisticRegression,
    vectorizer: TfidfVectorizer,
    texts: List[str],
    labels: List[str],
) -> dict:
    """Evaluate intent model on the full dataset."""

    X = vectorizer.transform(texts)
    y_pred = model.predict(X)

    accuracy = float(np.mean(y_pred == np.array(labels)))
    report = classification_report(labels, y_pred, output_dict=True, zero_division=0)

    log.info(f"Intent model accuracy on full dataset: {accuracy:.4f}")

    return {"accuracy": accuracy, "report": report}


def evaluate_entity(
    model: LogisticRegression,
    vectorizer: TfidfVectorizer,
    tokens: List[str],
    tags: List[str],
) -> dict:
    """Evaluate entity model on the full dataset."""

    X = vectorizer.transform(tokens)
    y_pred = model.predict(X)

    accuracy = float(np.mean(y_pred == np.array(tags)))
    report = classification_report(tags, y_pred, output_dict=True, zero_division=0)

    log.info(f"Entity model accuracy on full dataset: {accuracy:.4f}")

    return {"accuracy": accuracy, "report": report}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point for the training script."""

    import argparse

    parser = argparse.ArgumentParser(description="Train Meridin ML models")
    parser.add_argument(
        "--intent-only", action="store_true",
        help="Only train the intent classifier",
    )
    parser.add_argument(
        "--entity-only", action="store_true",
        help="Only train the entity extractor",
    )
    parser.add_argument(
        "--eval-only", action="store_true",
        help="Only evaluate existing models (no training)",
    )
    parser.add_argument(
        "--test-size", type=float, default=0.2,
        help="Fraction of data to use for testing (default: 0.2)",
    )
    parser.add_argument(
        "--random-state", type=int, default=42,
        help="Random seed for reproducibility (default: 42)",
    )

    args = parser.parse_args()

    intent_model = intent_vectorizer = None
    entity_model = entity_vectorizer = None

    # ------------------------------------------------------------------
    # Intent classifier
    # ------------------------------------------------------------------
    if not args.entity_only:
        log.info("=" * 60)
        log.info("Training Intent Classifier")
        log.info("=" * 60)

        if args.eval_only:
            intent_model, intent_vectorizer, _, _ = load_models()
            texts, labels = load_intent_data()
            metrics = evaluate_intent(intent_model, intent_vectorizer, texts, labels)
        else:
            texts, labels = load_intent_data()
            intent_model, intent_vectorizer, metrics = train_intent_classifier(
                texts, labels,
                test_size=args.test_size,
                random_state=args.random_state,
            )
            log.info(f"Intent model classes: {list(intent_model.classes_)}")

    # ------------------------------------------------------------------
    # Entity extractor
    # ------------------------------------------------------------------
    if not args.intent_only:
        log.info("=" * 60)
        log.info("Training Entity Extractor")
        log.info("=" * 60)

        if args.eval_only:
            _, _, entity_model, entity_vectorizer = load_models()
            tokens, tags = load_entity_data()
            metrics = evaluate_entity(entity_model, entity_vectorizer, tokens, tags)
        else:
            tokens, tags = load_entity_data()
            entity_model, entity_vectorizer, metrics = train_entity_extractor(
                tokens, tags,
                test_size=args.test_size,
                random_state=args.random_state,
            )
            log.info(f"Entity model classes: {list(entity_model.classes_)}")

    # ------------------------------------------------------------------
    # Save models
    # ------------------------------------------------------------------
    if not args.eval_only:
        log.info("=" * 60)
        log.info("Saving models")
        log.info("=" * 60)
        save_models(intent_model, intent_vectorizer, entity_model, entity_vectorizer)

    log.info("=" * 60)
    log.info("Training complete!")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
