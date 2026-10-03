import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from qdrant_client import QdrantClient, models

from retrieval.embedder import LogEmbedder


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

QDRANT_URL = "http://localhost:6333"

COLLECTION_NAME = "opscopilot_logs"

BATCH_SIZE = 128

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_INPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "openstack_logs.jsonl"
)


# ---------------------------------------------------------
# Timestamp utilities
# ---------------------------------------------------------

def parse_timestamp(timestamp: str) -> datetime:
    """
    Convert an ISO timestamp into a timezone-aware datetime.
    """

    timestamp = timestamp.replace("Z", "+00:00")

    dt = datetime.fromisoformat(timestamp)

    if dt.tzinfo is None:
        dt = dt.replace(
            tzinfo=timezone.utc
        )

    return dt


def timestamp_to_epoch(timestamp: str) -> float:
    """
    Convert ISO timestamp into Unix epoch seconds.

    Numeric timestamps allow Qdrant to perform
    efficient range filtering.
    """

    return parse_timestamp(timestamp).timestamp()


# ---------------------------------------------------------
# Vector Store
# ---------------------------------------------------------

class VectorStore:

    def __init__(self):

        print(
            f"Connecting to Qdrant: {QDRANT_URL}"
        )

        self.client = QdrantClient(
            url=QDRANT_URL
        )

        self.embedder = LogEmbedder()

        self.ensure_collection()

    # -----------------------------------------------------
    # Collection
    # -----------------------------------------------------

    def ensure_collection(self):
        """
        Create the Qdrant collection if it doesn't exist.
        """

        collections = self.client.get_collections()

        existing_names = [
            collection.name
            for collection in collections.collections
        ]

        if COLLECTION_NAME in existing_names:

            print(
                f"Collection already exists: "
                f"{COLLECTION_NAME}"
            )

            return

        self.client.create_collection(
            collection_name=COLLECTION_NAME,

            vectors_config=models.VectorParams(
                size=self.embedder.dimension,
                distance=models.Distance.COSINE
            )
        )

        print(
            f"Created collection: "
            f"{COLLECTION_NAME}"
        )

    # -----------------------------------------------------
    # Point ID
    # -----------------------------------------------------

    def create_point_id(
        self,
        record: dict
    ) -> str:
        """
        Create a deterministic UUID for a log record.

        This prevents duplicate points if the same
        log file is indexed again.
        """

        unique_text = (
            f"{record.get('source', '')}|"
            f"{record.get('log_file', '')}|"
            f"{record.get('line_number', '')}|"
            f"{record.get('timestamp', '')}|"
            f"{record.get('message', '')}"
        )

        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                unique_text
            )
        )

    # -----------------------------------------------------
    # Indexing
    # -----------------------------------------------------

    def index_records(
        self,
        input_file: str | Path
    ):
        """
        Read JSONL logs and index them into Qdrant
        in batches.
        """

        input_file = Path(input_file)

        if not input_file.exists():

            raise FileNotFoundError(
                f"Input file not found: {input_file}"
            )

        batch_records = []

        total_indexed = 0

        print(
            f"Indexing logs from:\n{input_file}"
        )

        with input_file.open(
            "r",
            encoding="utf-8"
        ) as file:

            for line_number, line in enumerate(
                file,
                start=1
            ):

                try:

                    record = json.loads(line)

                except json.JSONDecodeError:

                    print(
                        f"Skipping invalid JSON "
                        f"at line {line_number}"
                    )

                    continue

                timestamp = record.get(
                    "timestamp"
                )

                message = record.get(
                    "message"
                )

                if not timestamp or not message:

                    continue

                batch_records.append(record)

                if len(batch_records) >= BATCH_SIZE:

                    self._index_batch(
                        batch_records
                    )

                    total_indexed += len(
                        batch_records
                    )

                    print(
                        f"Indexed "
                        f"{total_indexed} records..."
                    )

                    batch_records = []

        # Index remaining records
        if batch_records:

            self._index_batch(
                batch_records
            )

            total_indexed += len(
                batch_records
            )

        print()
        print(
            "Indexing complete."
        )

        print(
            f"Total records indexed: "
            f"{total_indexed}"
        )

    # -----------------------------------------------------
    # Batch indexing
    # -----------------------------------------------------

    def _index_batch(
        self,
        records: list[dict]
    ):
        """
        Convert a batch of logs into embeddings
        and upload them to Qdrant.
        """

        texts = [
            record["message"]
            for record in records
        ]

        vectors = self.embedder.embed_texts(
            texts
        )

        points = []

        for record, vector in zip(
            records,
            vectors
        ):

            timestamp = record["timestamp"]

            payload = {
                # Time information
                "timestamp": timestamp,

                "timestamp_epoch":
                    timestamp_to_epoch(
                        timestamp
                    ),

                # Log information
                "source":
                    record.get("source"),

                "service":
                    record.get("service"),

                "level":
                    record.get("level"),

                "entity_id":
                    record.get("entity_id"),

                "message":
                    record.get("message"),

                # File information
                "log_file":
                    record.get("log_file"),

                "line_number":
                    record.get("line_number"),

                # OpenStack information
                "pid":
                    record.get("pid"),

                "status":
                    record.get("status"),

                "response_time":
                    record.get("response_time"),

                # Incident information
                "incident_id":
                    record.get("incident_id"),

                "synthetic":
                    record.get(
                        "synthetic",
                        False
                    )
            }

            point = models.PointStruct(
                id=self.create_point_id(
                    record
                ),

                vector=vector,

                payload=payload
            )

            points.append(point)

        self.client.upsert(
            collection_name=COLLECTION_NAME,
            points=points
        )

    # -----------------------------------------------------
    # Search
    # -----------------------------------------------------

    def search_logs(
        self,
        query: str,
        limit: int = 5,
        start_time: str | None = None,
        end_time: str | None = None
    ):
        """
        Perform semantic search.

        Optional start_time and end_time allow
        retrieval to be restricted to an incident
        time window.
        """

        query_vector = (
            self.embedder.embed_text(query)
        )

        query_filter = None

        if start_time or end_time:

            conditions = []

            if start_time:

                conditions.append(
                    models.FieldCondition(
                        key="timestamp_epoch",

                        range=models.Range(
                            gte=
                            timestamp_to_epoch(
                                start_time
                            )
                        )
                    )
                )

            if end_time:

                conditions.append(
                    models.FieldCondition(
                        key="timestamp_epoch",

                        range=models.Range(
                            lte=
                            timestamp_to_epoch(
                                end_time
                            )
                        )
                    )
                )

            query_filter = models.Filter(
                must=conditions
            )

        results = self.client.query_points(

            collection_name=
                COLLECTION_NAME,

            query=query_vector,

            query_filter=query_filter,

            limit=limit,

            with_payload=True
        ).points

        return results

    # -----------------------------------------------------
    # Display results
    # -----------------------------------------------------

    def print_search_results(
        self,
        results
    ):
        """
        Display retrieved logs.
        """

        print()
        print(
            "Search Results"
        )

        print(
            "=" * 70
        )

        if not results:

            print(
                "No logs found "
                "in the requested window."
            )

            return

        for index, result in enumerate(
            results,
            start=1
        ):

            payload = result.payload

            print()
            print(
                f"Result {index}"
            )

            print(
                f"Score: "
                f"{result.score:.4f}"
            )

            print(
                f"Timestamp: "
                f"{payload.get('timestamp')}"
            )

            print(
                f"Source: "
                f"{payload.get('source')}"
            )

            print(
                f"Service: "
                f"{payload.get('service')}"
            )

            print(
                f"Level: "
                f"{payload.get('level')}"
            )

            print(
                f"Entity ID: "
                f"{payload.get('entity_id')}"
            )

            print(
                f"Message: "
                f"{payload.get('message')}"
            )

            if payload.get("status") is not None:

                print(
                    f"Status: "
                    f"{payload.get('status')}"
                )

            if payload.get(
                "response_time"
            ) is not None:

                print(
                    f"Response Time: "
                    f"{payload.get('response_time')}"
                )


# ---------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------

def main():

    parser = argparse.ArgumentParser(
        description=
        "OpsCopilot Qdrant Vector Store"
    )

    parser.add_argument(
        "--index",
        action="store_true",
        help=
        "Index OpenStack JSONL logs"
    )

    parser.add_argument(
        "--search",
        type=str,
        help=
        "Perform semantic log search"
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5
    )

    parser.add_argument(
        "--start-time",
        type=str,
        default=None
    )

    parser.add_argument(
        "--end-time",
        type=str,
        default=None
    )

    args = parser.parse_args()

    store = VectorStore()

    if args.index:

        store.index_records(
            DEFAULT_INPUT_FILE
        )

    if args.search:

        results = store.search_logs(

            query=args.search,

            limit=args.limit,

            start_time=args.start_time,

            end_time=args.end_time
        )

        store.print_search_results(
            results
        )


if __name__ == "__main__":
    main()