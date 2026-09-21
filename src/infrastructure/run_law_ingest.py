import logging
from qdrant_law_index import QdrantLawIndex

logging.basicConfig(level=logging.INFO)

def main():
    idx = QdrantLawIndex.from_settings()
    try:
        plan = idx.build_plan()
        print("plan:", plan.as_dict())

        status = idx.status(plan)
        print("status:", status.as_dict())

        # 1) dry run
        print("dry run:", {k: v.as_dict() for k, v in idx.ingest(plan, dry_run=True).items()})

        # 2) real run (canonical refresh + local embedding)
        stats = idx.ingest(plan, targets=("canonical", "local"))
        for name, s in stats.items():
            print(name, s.as_dict())

        # 3) validate
        print("validate:", idx.validate(plan).as_dict())
    finally:
        idx.close()

if __name__ == "__main__":
    main()