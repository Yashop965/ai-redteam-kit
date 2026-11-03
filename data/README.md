# Data policy

## BrowseComp-Plus seed bank (decrypted locally, NOT committed)

The 830-question seed bank from **Tevatron/browsecomp-plus** (ACL 2026, derived from
**OpenAI BrowseComp**) is intentionally **not shipped** in this repo: upstream stores every
text field XOR-obfuscated with a public canary to keep benchmark answers from being scraped
off HuggingFace. We honor that — the repo ships the *recipe* instead.

Regenerate locally in two commands:

```bash
pip install pyarrow
python scripts/mine_bcp.py
# -> data/browsecomp_plus_decrypted.jsonl  (queries, answers, gold + evidence docs)
# -> data/bcp_shortlist.json                (top-20 form-constraint shortlist)
```

`scripts/mine_bcp.py` downloads the 4 obfuscated parquet files from the dataset's public
HuggingFace endpoint and decrypts with the same public canary that the upstream repo
(`texttron/BrowseComp-Plus`, `scripts_build_index/decrypt_dataset.py`) publishes. The two
output files are gitignored.

## bcp_* candidates

The form-constraint miner (`BAD_IMG` / `BAD_TIME` / short-proper-noun filters in
`scripts/mine_bcp.py`) is the same miner that produced the `bcp_*` candidate entries used in
this project's assessment. To re-add a shortlisted question to `candidates.json`, copy the
shortlist record into the candidate schema (id, type, pinned_question, golden, verify_queries,
source_urls, justification) and run `python cli.py author --only <id>`.

## Credit

OpenAI (BrowseComp benchmark), Tevatron (BrowseComp-Plus). Keep attribution when reusing any
question or evidence document.
