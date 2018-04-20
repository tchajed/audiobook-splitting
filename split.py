#!/usr/bin/env python3

# split.py --- Splitting an audiobook into per-chapter tracks

# Copyright © 2016 Tej Chajed

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import print_function

import subprocess
import datetime
import re
import sys
import os
from os import path

MIN_SILENCE_DURATION_SEC = 1.5
MAXIMUM_CHAPTER_HEADER_SEC = 2

class Silence:
    # start and end are in seconds
    def __init__(self, start, end):
        self.start = start
        self.end = end

    @property
    def duration(self):
        return self.end - self.start

    def __repr__(self):
        return "{} - {}".format(
                datetime.timedelta(seconds=round(self.start)),
                datetime.timedelta(seconds=round(self.end)))

class SilenceGroup:
    def __init__(self, silences):
        self.silences = silences

    @property
    def start(self):
        if len(self.silences) == 1:
            return 0
        return self.silences[0].end

    @property
    def end(self):
        return self.silences[-1].start

    @property
    def duration(self):
        return self.end - self.start

CHAPTER_PROP = re.compile("(?P<prop>.*?): (?P<val>.*)")

class Chapter:
    def __init__(self, fname, name, start):
        self.fname = fname
        self.name = name
        self.start = start

    @classmethod
    def from_lines(cls, lines, fname):
        props = {"fname": fname}
        for line in lines:
            m = CHAPTER_PROP.match(line.strip())
            if m:
                prop = m.group("prop").lower()
                val = m.group("val")
                if prop in ["start"]:
                    val = float(val)
                props[prop] = val
        fname = props["fname"]
        name = props.get("name", "").strip()
        start = props["start"]
        if name != "" and name != "*spurious*":
            return cls(fname, name, start)
        return None

    def __repr__(self):
        return "{} {} @ {}".format(self.fname, self.name,
                datetime.timedelta(seconds=round(self.start)))

SILENCE_START = re.compile(b"\[silencedetect .*?\] " +
        b"silence_start: (?P<start>[0-9.]*)")
SILENCE_END = re.compile(b"\[silencedetect .*?\] " +
        b"silence_end: (?P<end>[0-9.]*)")

def detect_silences(fname):
    output = subprocess.check_output([
        "ffmpeg", "-i", fname,
        "-hide_banner",
        "-af",
        "silencedetect=d={}:noise=-30dB".format(
            MIN_SILENCE_DURATION_SEC),
        "-f", "null", "-"], stderr=subprocess.STDOUT)
    silences = []
    silence_start = None
    for line in output.split(b"\n"):
        m = SILENCE_START.search(line)
        if m:
            silence_start = float(m.group("start"))
        m = SILENCE_END.search(line)
        if m:
            silence_end = float(m.group("end"))
            silences.append(Silence(silence_start, silence_end))
            silence_start = None
    return silences

def metadata_args(metadata):
    args = []
    for key, val in metadata.items():
        args.extend(["-metadata", '{}={}'.format(key, val)])
    return args

def cut_audio(fname, start, duration, output, metadata, nop=False):
    """ Call ffmpeg to subselect some audio.

    Copies duration seconds of audio, beginning at start, from fname and
    outputs to output.

    If nop is False, do nothing and return the computed invocation of ffmpeg.
    """
    start_args = ["-ss", str(start)] if start else []
    duration_args = ["-t", str(duration)] if duration else []
    args = ["ffmpeg", "-y",
            "-i", fname] + \
                    metadata_args(metadata) + \
                    ["-loglevel", "quiet"] + \
                    ["-acodec", "copy"] + \
                    start_args + \
                    duration_args + \
                    [output]
    if nop:
        return args
    subprocess.check_call(args, stderr=subprocess.STDOUT)


def concatenate_audio(fnames, output, metadata, nop=False):
    """ Call ffmpeg to concatenate audio files. """
    args = ["ffmpeg", "-y",
            "-i", "concat:" + "|".join(fnames)] + \
                    metadata_args(metadata) + \
                    ["-c", "copy",
                            "-loglevel", "quiet",
                            output]
    if nop:
        return args
    subprocess.check_call(args, stderr=subprocess.STDOUT)


def group_silences(silences):
    silence_groups = []
    silence_group = []
    for silence, prev_silence in zip(silences, [None] + silences):
        if (not prev_silence or
                silence.start - prev_silence.end < MAXIMUM_CHAPTER_HEADER_SEC):
            # accumulate silence group
            silence_group.append(silence)
        else:
            # clear and append
            silence_groups.append(silence_group)
            silence_group = [silence]
    silence_groups.append(silence_group)
    return silence_groups

def load_chapters(fname, f):
    """ Load chapters associated with fname from chapters given in f.

    fname should be a plain string while f is a file handle to chapter info.
    """
    chapters = []
    lines = []
    for line in f:
        line = line.strip()
        if line == "CHAPTER":
            lines = []
        elif line == "END":
            chapter = Chapter.from_lines(lines, fname)
            if chapter:
                chapters.append(chapter)
        lines.append(line)
    return chapters


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
            formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    subparsers = parser.add_subparsers(help="command")

    parser_find = subparsers.add_parser("find", help="find chapter headings")
    parser_find.set_defaults(cmd="find")
    parser_find.add_argument("input")

    parser_split = subparsers.add_parser("split", help="split audio")
    parser_split.set_defaults(cmd="split")
    parser_split.add_argument("-o", "--output-dir",
            help="output directory for chapter audio")
    parser_split.add_argument("-c", "--commands",
            default=None,
            help="prefix for command output files")
    parser_split.add_argument("-t", "--title",
                              default="Book",
                              help="Title to add to output metadata")
    parser_split.add_argument("audios", nargs="+",
            help="audio files with chapters.txt annotations")

    args = parser.parse_args()

    def chapter_file(fname):
        return fname + "-chapters.txt"

    if args.cmd == "find":
        silences = [SilenceGroup(group) for
                group in group_silences(detect_silences(args.input))
                if len(group) > 1 or
                group[0].start < MAXIMUM_CHAPTER_HEADER_SEC]
        chapters = {}
        out_fname = chapter_file(args.input)
        if path.exists(out_fname):
            with open(out_fname, "r") as f:
                chapter_list = load_chapters(args.input, f)
                for chapter in chapter_list:
                    chapters[chapter.start] = chapter
        with open(out_fname, "w") as f:
            for group in silences:
                f.write("CHAPTER\n")
                f.write("CMD: ffplay -i \"{}\" -ss {:.2f} -t {:.2f} {}\n".format(
                    args.input, group.start - 0.1, group.duration + 0.2,
                    "-autoexit -loglevel quiet"))
                name = ""
                if group.start in chapters:
                    name = chapters[group.start].name
                f.write("NAME: {}\n".format(name))
                f.write("START: {}\n".format(group.start))
                for silence in group.silences:
                    f.write("{} ... {}\n".format(silence.start, silence.end))
                f.write("END\n\n")
    if args.cmd == "split":
        audio_chapters = []
        for fname in args.audios:
            with open(chapter_file(fname)) as f:
                audio_chapters.append( (fname, load_chapters(fname, f)) )
        outputs = []
        current_chapter = {"segments": [], "name": "preamble"}
        for fname, chapters in audio_chapters:
            if not chapters:
                current_chapter["segments"].append({
                    "fname": fname,
                    "start": None,
                    "duration": None})
                continue
            # add first chapter to previous
            current_chapter["segments"].append({
                "fname": fname,
                "start": None,
                "duration": chapters[0].start})
            # ... and save it
            outputs.append(current_chapter)
            # add middle chapters directly
            for i, chapter in enumerate(chapters[:-1]):
                outputs.append({
                    "segments": [{
                        "fname": chapter.fname,
                        "start": chapter.start,
                        "duration": chapters[i+1].start - chapter.start,
                        }],
                    "name": chapter.name })
            last_chapter = chapters[-1]
            current_chapter = {
                    "segments": [{
                        "fname": last_chapter.fname,
                        "start": last_chapter.start,
                        "duration": None,
                        }],
                    "name": last_chapter.name,
                    }
        outputs.append(current_chapter)

        cut_f = None
        concat_f = None
        nop = False
        if args.commands:
            cut_f = open(args.commands + "-1-cut", "w")
            concat_f = open(args.commands + "-2-concat", "w")
            nop = True

        def shellquote(s):
            if re.match("^[a-zA-Z0-9-_.]*$", s):
                return s
            s = s.replace("\\", "\\\\")
            s = s.replace("$", "\$")
            s = s.replace("'", "\\'")
            return "'{}'".format(s)

        def write_cmd(cmd, f):
            if f is None:
                return
            quoted = [cmd[0]] + [shellquote(arg) for arg in cmd[1:]]
            cmdline = " ".join(quoted)
            f.write(cmdline + "\n")

        def cut_segment(segment, output, metadata):
            write_cmd(cut_audio(segment["fname"],
                    segment["start"],
                    segment["duration"],
                    output,
                    metadata,
                    nop), cut_f)

        for num, output in enumerate(outputs[1:]):
            metadata = {"title": "{} ch{} - {}".format(
                args.title, num, output["name"].capitalize()),
                "track": num+1}
            out_fname = "ch{:02}-{}".format(num, output["name"])
            out_path = path.join(args.output_dir, out_fname + ".mp3")
            segments = output["segments"]
            if len(segments) == 1:
                print("writing", out_fname + ".mp3")
                sys.stdout.flush()
                cut_segment(segments[0], out_path, metadata)
            else:
                def tmp_name(i):
                    tmp_fname = "{}-tmp{}.mp3".format(out_fname, i)
                    return path.join(args.output_dir, tmp_fname)
                for i, segment in enumerate(segments):
                    cut_segment(segment, tmp_name(i), {})
                print("joining", out_fname + ".mp3")
                cmd = concatenate_audio(
                        [tmp_name(i) for i in range(len(segments))],
                        out_path, metadata, nop)
                write_cmd(cmd, concat_f)
                if not nop:
                    for i in range(len(segments)):
                        os.remove(tmp_name(i))
