#!/usr/bin/env python3
"""Recalculate published confirmed scores from frozen 0.2.0 scoring inputs.
Standard library only. Do not change frozen weights or scoring after publication."""
import csv,json,random
from collections import defaultdict,Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def csv_read(name):
 with (ROOT/name).open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
weights={r["criterion"]:int(r["weight"]) for r in csv_read("SCORING_MODEL.csv")}
rows=csv_read("SCORE_MATRIX.csv")
results=json.loads((ROOT/"RESULTS.json").read_text(encoding="utf-8"))
assert len(rows)==170 and sum(weights.values())==100
assert {r["metric_code"] for r in rows}=={r["metric_code"] for r in csv_read("RUBRICS.csv")}
score=defaultdict(float)
groups=defaultdict(lambda:defaultdict(float))
for r in rows:
 pts=float(r["confirmed_points"]);m=float(r["max_points"])
 assert 0<=pts<=m
 score[r["candidate_id"]]+=pts
 groups[r["candidate_id"]][r["criterion"]]+=pts
for r in results["participants"]:
 assert score[r["candidateId"]]==r["confirmedScore"],r
print("Scores OK:",[(r["name"],r["confirmedScore"]) for r in results["participants"]])

# Independently reproduce 5000 possible weight adjustments, same documented random seed.
randomizer=random.Random(20261104)
ids=[r["candidateId"] for r in results["participants"]]
counts=Counter();min_margin=1e9
for _ in range(5000):
   raw={g:weights[g]*randomizer.uniform(.8,1.2) for g in weights}
   normalized={g:100*v/sum(raw.values()) for g,v in raw.items()}
   new_scores={cid:sum(groups[cid][g]*normalized[g]/weights[g] for g in weights) for cid in ids}
   leader=max(new_scores,key=new_scores.get);counts[leader]+=1
   min_margin=min(min_margin,new_scores["C01"]-new_scores["C02"])
assert counts["C01"]==5000,counts
print("Sensitivity OK: 5000/5000 confirmed-score leaders C01; min margin:",round(min_margin,4))
