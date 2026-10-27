"""Your own input files, by chapter. Copy to batkol/sources_local.py (git-ignored) and fill in.

Paths are relative to the rclone remote `gdrive:`. Each language has:
  audio  one file, or (folder, rclone glob) resolved by `python -m batkol.sources fetch <chapter>`
  cut    optional: for a whole-book file, the chapter title to cut at its chapter marks
  text   where the chapter text is written, under ~/work
  epubs  {name: path} of one or more editions, or (folder, glob); batkol.edition picks the text
Index keys are <lang>_<chapter>, e.g. nl_ch01, en_b2ch01.
"""
NL = "batkol/<target-language audiobook folder>"
EN = "batkol/<native-language audiobook folder>"

CHAPTERS = {
    "ch01": dict(
        nl=dict(audio=f"{NL}/<book 1>/<chapter 1>.opus", text="text/nl.ch01.txt",
                epubs={"nl_a": f"{NL}/<book 1>.epub"}),
        en=dict(audio=f"{EN}/<book 1>/<chapter 1>.opus", text="text/en_a.ch01.txt",
                epubs={"en_a": f"{EN}/<book 1>.epub"})),
    # a whole-book audio file: give the chapter title and it is cut from the chapter marks
    "b2ch01": dict(
        nl=dict(audio=(f"{NL}/<book 2>", "01*.opus"), text="text/nl.b2ch01.txt",
                epubs={"nl_b2_a": f"{NL}/<book 2>.epub"}),
        en=dict(audio=f"{EN}/<book 2>.m4b", cut="<chapter 1 title>", text="text/en.b2ch01.txt",
                epubs={"en_b2_a": f"{EN}/<book 2>.epub"})),
}

PIMS_L01 = "batkol/<course folder>/Lesson01.mp3"  # instruction phrases ("How do you say…"); optional
