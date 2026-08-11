.PHONY: demo eval live clean

demo:            ## Offline run against synthetic fixtures, no keys needed
	python -m src.run --mock

eval: demo       ## Score the last run against human labels
	python eval/run_eval.py --run out/shortlist.json

live:            ## Live run: make live CITY=Lisbon ZONE="Principe Real" LAT=38.7167 LNG=-9.15
	python -m src.run --city "$(CITY)" --zone "$(ZONE)" --lat $(LAT) --lng $(LNG)

clean:
	rm -rf out/ __pycache__ src/__pycache__
