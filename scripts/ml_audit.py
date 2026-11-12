#!/usr/bin/env python3
"""Export actual reproducible model diagnostics without accessing service secrets."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import main
main.initialize()
main.train()
result={'metrics':main.metrics,'scenario_examples':{}}
for storm in (0,80,100):
 result['scenario_examples'][str(storm)]=[
  {k:v for k,v in main.route_view(r,24.8,storm).items() if k in ('id','delay_hours','total_hours','co2_kg','wind','wave','load','delay_change_hours','risk_level')}
  for r in main.ROUTES]
result['load_examples']={str(load):main.route_view(main.ROUTES[0],24.8,0,load)['delay_hours'] for load in (30,50,80,99)}
output=Path(__file__).resolve().parents[1]/'docs'/'ml_metrics.json'
output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(output)
print(json.dumps({k:main.metrics[k] for k in ('version','mae_hours','rmse_hours','r2','baseline_mae_hours','test_interval_coverage')},ensure_ascii=False))
