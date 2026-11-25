.PHONY: test demo report lint
test:   ; python -m unittest discover -s tests -t . -v
demo:   ; python -m sentinel demo && echo "open demo-report.html in a browser"
verify: ; python -m sentinel verify
