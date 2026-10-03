from sentence_transformers import SentenceTransformer


class LogEmbedder:
    """
    Converts log messages into vector embeddings.

    The embeddings allow OpsCopilot to perform semantic
    similarity search over log messages.
    """

    MODEL_NAME = "all-MiniLM-L6-v2"

    # Shared model instance for the entire Python process.
    _model = None
    _dimension = None

    def __init__(self):
        # Load the model only once.
        if LogEmbedder._model is None:
            print(f"Loading embedding model: {self.MODEL_NAME}")

            LogEmbedder._model = SentenceTransformer(self.MODEL_NAME)

            LogEmbedder._dimension = (
                LogEmbedder._model.get_embedding_dimension()
            )

            print(
                f"Embedding dimension: {LogEmbedder._dimension}"
            )

        self.model = LogEmbedder._model
        self.dimension = LogEmbedder._dimension

    def embed_text(self, text: str) -> list[float]:
        """Convert a single log message into an embedding."""

        embedding = self.model.encode(
            text,
            normalize_embeddings=True
        )

        return embedding.tolist()

    def embed_texts(
        self,
        texts: list[str]
    ) -> list[list[float]]:
        """Convert multiple log messages into embeddings."""

        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False
        )

        return embeddings.tolist()


if __name__ == "__main__":

    embedder = LogEmbedder()

    example_text = (
        "Nova failed to process the request"
    )

    vector = embedder.embed_text(example_text)

    print(f"Vector length: {len(vector)}")
    print(f"First 5 values: {vector[:5]}")