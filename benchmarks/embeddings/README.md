# Multilingual embedding benchmark

This benchmark compares open multilingual models against the actual ERP catalog without committing
the private CSV files or inquiry corpus. It uses French ERP translations as automatically labelled
cross-language queries and can add manually reviewed, already-normalized inquiry labels from JSONL.
Master/pseudo records are excluded with the same eligibility rule as production. With the supplied
August files, the automatic benchmark contains 1,645 offerable catalogue candidates and 801 French
queries.

It deliberately does not parse SharePoint, Outlook, PDFs, or supplier datasheets. That belongs to
the extraction workstream. Its optional label format is the structured handover boundary:

```json
{"query_id":"case-1","text":"...","expected_item_number":"410001001","domain":"equipment","language":"fr"}
```

Run this in an Azure Container Apps Job or another adequately sized cloud runner—not on the project
laptop:

```bash
python -m pip install -r benchmarks/embeddings/requirements.txt
python benchmarks/embeddings/run.py \
  --articles /secure-input/Artikeldaten.csv \
  --translations /secure-input/Artikeluebersetzungen.csv \
  --labels /secure-input/reviewed-labels.jsonl \
  --compute-cost-per-hour <price-of-the-selected-azure-runner> \
  --output /secure-output/embedding-report.json
```

For Azure, build `benchmarks/embeddings/Dockerfile` from the repository root. The resulting image is
separate from the web application so the production API does not carry PyTorch or model weights.

The default free-first comparison is:

1. `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
2. `BAAI/bge-m3`
3. `intfloat/multilingual-e5-large-instruct`

“Free” means there is no per-vector API fee: the model weights run in our own job. Azure CPU/GPU,
temporary storage, and model-download traffic still cost money. MiniLM is the low-cost baseline;
BGE-M3 and E5-large are deliberately more expensive quality candidates. The web application does
not load any of them.

The runner applies query/document roles correctly. E5 models receive their required query versus
passage prefixes, and the instruct variant receives a medical procurement retrieval instruction.
`--batch-size` controls the actual encoder batch size rather than merely annotating the report.

The report records model/revision, dimensions, Recall@1/3/10, MRR, encoding time, throughput, vector
storage, optional measured compute-cost estimate, and the first 100 failures. A model failure is
recorded without discarding completed results from the other models. Review failures involving
strength, dosage form, size, sterility, and packaging—not only the aggregate score. Pin the winning
model to a concrete upstream revision before activating it in the database. A paid model should only
be added as a baseline after these results are reviewed and its EU hosting, retention, no-training
terms, and expected request volume are known.

After approval, use the same image with an overridden entry point to initialize and incrementally
maintain product embeddings:

```bash
python -m app.catalog.embedding_worker \
  --model <approved-model> \
  --revision <immutable-revision> \
  --batch-size 32
```

The worker registers one active model, queues every missing current product version, recovers stale
jobs, and writes normalized vectors to pgvector. Future catalog imports queue only new or
text-changed offerable variants. Quantity-only changes do not trigger model inference.
