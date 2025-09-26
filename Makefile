.PHONY: test
test:
	cat testing/DocumentHeader.org > testing/DocumentHeader
	cat testing/DocumentInfo.org > testing/DocumentInfo
	python3 main.py testing file:Mods\MyMod.SC2Mod
	diff --binary testing/DocumentInfo testing/DocumentInfo.exp
	diff --binary testing/DocumentHeader testing/DocumentHeader.exp
	rm testing/DocumentHeader testing/DocumentInfo
