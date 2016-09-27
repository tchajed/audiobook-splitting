# Splitting audiobooks into chapters

Tools to re-split audiobooks into a file per chapter. Chapters are identified by spoken headings. Then the user annotates chapters by listening to the chapter headings and writing them down. Finally, the source files are split into a file per chapter, with a filename containing the chapter number and name.

The workflow is extremely hacky, but it works for me for _A Song of Ice and Fire_, where chapter headings contain the POV character and thus are meaningful and easily identified. If you think some part of this is useful but the code is too specific, please open an issue describing what your situation looks like and I'd be happy to start generalizing! Likewise, if the process is too complicated but you think this would be useful feel free to open an issue.

In particular, this is what my situation looks like. The book is split into around 35, 1 hour 15 minute-long parts. Each part contains multiple chapters, and occasionally the last chapter in a part is continued in the next. Chapters are introduced by the name of the POV character ("Eddard", "Arya", etc). In the end, I want a file per chapter with its number and the POV character, matching the affordances I get from the digital version of the book.

## Workflow

In greater detail, here's how to split and audiobook with `split.py`.

1. Run `split.py find` on every `.mp3` file, producing a bunch of files called `$file-chapters.txt`. I do this using GNU parallel (after adding the path to audiobook-splitting to my `$PATH`):
    ```
    $ parallel --eta split.py find ::: *.mp3
    ```

    This takes around 5 minutes on a 50 hour audiobook for me, on 4 cores.

    Chapters are identified by looking for a heading, which is a short segment of audio surrounded by relatively long periods of silence. Silences need to be longer than `MIN_SILENCE_DURATION_SEC` and headers can be no longer than `MAXIMUM_CHAPTER_HEADER_SEC`, constants defined at the top of `split.py`.
2. Now you need to add a name annotation to every chapter. Currently, chapters with empty names and the special marker `*spurious*` are ignored - that is, they are not treated as split points.

    Note that each chapter has a block of text with
    * CHAPTER/END begin and end markers - these are needed for parsing.
    * A `NAME: ` property for you to fill in.
    * A `CMD: ` property giving a commandline for `ffplay` (part of ffmpeg - on OS X, Homebrew by default does not include this program, but you can get it with `brew install --with-ffplay ffmpeg`) that plays the heading of the chapter.
    * A `START: ` property giving the offset (in seconds) into the file where this heading starts. This determines the split point for this chapter.
    * (for debugging) The silences surrounding this heading, as offsets in seconds into the file.

    To make the process of running each command and writing down the name more convenient, I used the following Vim macro:

    `:let @q="/CMD\rW\"ay$j$:!\<C-R>a\r"`

    After running this command, `@q` will go to the next command, run it, and leave the cursor at the NAME line for you to enter the chapter name.
3. Once all the chapter files are filled in, we need to split the original files:

   ```
   $ mkdir chapters
   $ split.py split -o chapters -t "A Storm of Swords" *.mp3
   ```

   This will work, but is single threaded and slow. Instead, we can have `split.py` simply compute the `ffmpeg` commands needed and run them in parallel (pun intended):

   ```
   $ split.py split -c commands -o chapters -t "A Storm of Swords" *.mp3
   $ parallel :::: commands-1-cut
   $ parallel :::: commands-2-concat
   $ rm chapters/*-tmp*.mp3
   ```

   Note that the order of `*.mp3` files given is significant, since it determines what file the continuation of a chapter comes from, as well as the overall ordering.

   The `-c <prefix>` option creates files `<prefix>-1-cut` and `<prefix>-2-concat` - the first only segments files, while the latter re-combines chapters that were split across file boundaries. Both of these operations are very fast: on my laptop, cutting takes 30s for a 50 hour audiobook while concatenation takes 10s.

To make debugging easier, `split.py find` actually reads any existing chapters.txt file and saves names in it, to avoid losing work - if the parameters there already work, though, there should be no need to take advantage of this. The output `mp3` files are named `ch{num}-{name}.mp3` and are tagged with a track number (the same num) and are titled `{title} ch{num} - {Name}`, where `{Name}` is the chapter name with the first letter capitalized.
