#!/usr/bin/env python3
# this module implements an interface (and several implementations), depending
# on what libraries you have available) to convert frame folders into animations

import os, shutil
from abc import ABC, abstractmethod
from inspect import isclass
from packaging import version

def all_animators():
  return [
    g for g in globals().values()
    if isclass(g) and GCAnimator in g.mro() and g != GCAnimator
  ]

def supported_animators():
  return [a for a in all_animators() if a.available()[0]]

# in case we're actually run
def show_info():
  print("Here's the list implemented animators:\n")
  for anim in all_animators():
    av = "yes!" if anim.available() else "nope =/"
    fmts = ", ".join(anim.available_formats())
    print(
      f"==> \"{anim.name()}\" ({anim.__name__}):\n"
      f"  -> Available: {av}\n"
      f"  -> Status: {anim.available()[1]}\n"
      f"  -> Formats supported: {fmts}\n"
    )

# abstract class used as an interface by the main module
class GCAnimator(ABC):
  def __init__(self, frame_dir, params):
    if not self.__class__.available():
      n = self.__class__.name()
      raise ModuleNotFoundError(f"Animation module {n} not available!")
    self.frame_dir = frame_dir
    self.params = params

  # returns a short name
  @classmethod
  @abstractmethod
  def name(cls):
    pass

  # returns a quick description
  @classmethod
  @abstractmethod
  def description(cls):
    pass

  # tests if the module is available, returns a (bool, str)
  @classmethod
  @abstractmethod
  def available(cls):
    pass

  # returns available output formats
  @classmethod
  @abstractmethod
  def available_formats(cls):
    pass

  # actually does the animation work
  @abstractmethod
  def _animate(self, fmt, output_file_name):
    pass

  # but this one does checks and whatnot
  def animate(self, output_file_name, fmt = None, overwrite = True):
    if fmt is None:
      for avf in self.available_formats():
        if output_file_name.lower().endswith(avf):
          fmt = avf
          break
    if fmt is None:
      raise ValueError(
        f"Could not determine format from filename \"{output_file_name}\"!"
      )
    fmt = fmt.lower()
    if os.path.exists(output_file_name) and not overwrite:
      raise IOError("Output file exists")
    if fmt not in self.__class__.available_formats():
      n = self.__class__.name()
      raise ValueError(f"Unsupported fmt {fmt} for animator {n}!")
    if not output_file_name.lower().endswith(f".{fmt}"):
      output_file_name += f".{fmt}"
    return self._animate(output_file_name, fmt)

  # returns the range of frames
  def frame_range(self):
    return range(1, self.params["num_frames"]+1)

  # access a single frame's file name
  def frame_path(self, nframe):
    if nframe not in self.frame_range():
      raise ValueError(f"Frame #{nframe} is out of bounds!")
    return os.path.join(self.frame_dir.name, f"frame-{nframe:05d}.png")


# built-in animator, generates GIFs only using Pillow... always available!
class PillowGIF(GCAnimator):
  # returns a short name
  @classmethod
  def name(cls):
    return "PIL.Image GIF output"

  # returns a quick description
  @classmethod
  def description(cls):
    return "Uses the PIL (Pillow) Image module. Can only produce GIFs."

  # tests if the module is available
  @classmethod
  def available(cls):
    try:
      image_module = __import__("PIL").Image
      pv = image_module.__version__
      mv = "3.4"
      if version.parse(pv) < version.parse(mv):
        # Pillow releases before 3.4 can't do this
        return (False, f"Pillow version is {pv}, need at least {mv}!")
      else:
        return (True, f"Import successful, version {mv} is good enough.")
    except Exception as e:
      en = e.__class__.__name__
      return (False, f"{en} caught while importing Image from PIL!")

  # returns available output formats
  @classmethod
  def available_formats(cls):
    return ["gif"]

  # actually does the animation work
  def _animate(self, output_file_name, fmt):
    # we gotta load all images at once... this ought to suck.
    from PIL import Image
    fr = self.frame_range()
    frames = [Image.open(self.frame_path(n)).convert("RGB") for n in fr]
    if not len(frames):
      raise IndexError("Empty list?")
    fps = self.params["fps"]
    frames[0].save(
      output_file_name,
      save_all = True,
      append_images = frames[1:],
      duration = max(10, 1000//self.params["fps"]),
      optimize = True,
      loop = 0,
      comment = "Made with Gifception"
    )
    return True


# this one has waaay more resources, but requires ffmpeg.
class FFmpegBindings(GCAnimator):
    # returns a short name
    @classmethod
    def name(cls):
      return "FFmpeg via ffmpeg-python"

    # returns a quick description
    @classmethod
    def description(cls):
      return (
        "Uses the ffmpeg-python package to write just about any fmt.\n"
        "Efficient and nice. Requires a working FFmpeg install, though."
      )

    # tests if the module is available
    @classmethod
    def available(cls):
      try:
        ffmpeg_module = __import__("ffmpeg")
        if shutil.which("ffmpeg") is not None:
          return (True, "Both an ffmpeg command and ffmpeg-python detected.")
        else:
          return (False, "ffmpeg-python is installed, but no ffmpeg in PATH!")
      except Exception as e:
        en = e.__class__.__name__
        return (False, f"{en} caught while importing from ffmpeg-python!")

    # returns available output formats
    @classmethod
    def available_formats(cls):
      return ["gif", "webm"]

    # actually does the animation work
    def _animate(self, output_file_name, fmt):
      import ffmpeg
      # input spec
      in_args = {
        "pattern_type": "glob",
        "framerate": self.params["fps"]
      }
      # output spec
      out_args = {
        #"r": self.params["fps"]
      }
      if fmt == "gif":
        out_args["pix_fmt"] = "rgb24"
      # ffmpeg magic
      (
        ffmpeg.input(self.frame_dir.name + "/*.png", **in_args)
        .filter("fps", fps = self.params["fps"], round = "up")
        .output(output_file_name, **out_args)
        .run(overwrite_output = True, quiet = True)
      )


if __name__ == "__main__":
  print("This is a module! But while you're here...", end="\n...")
  show_info()
