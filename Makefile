.PHONY: test
test:
	cat testing/DocumentHeader.org > testing/DocumentHeader
	cat testing/DocumentInfo.org > testing/DocumentInfo
	python3 main.py testing
	diff --binary testing/DocumentInfo*
	diff --binary testing/DocumentHeader*
	rm testing/DocumentHeader testing/DocumentInfo