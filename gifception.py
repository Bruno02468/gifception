#!/usr/bin/env python3
# written by bruno02468
# implements the relevant tooling for making them GIFs

# Pillow is required
try:
  from PIL import Image, ImageDraw
except:
  print("Install Pillow. May I suggest `pip3 install pillow`?")
  raise

# some standard libs too
import sys, os, operator, math, copy
from multiprocessing import Process, Queue
from tempfile import TemporaryDirectory


# why not
class GifceptionException(Exception):
  pass

# extends image with anchor capabilities and zoom-in and whatnot, all in-place
class AnchoredImage():
  # configs for anchored images
  _default_config = {
    "max_pixels": 8e8,
    "resampler": Image.BICUBIC
  }

  def __init__(self, img, anchor = (0.5, 0.5), relative = True, config = None):
    self.img = img
    self.config = config or copy.copy(AnchoredImage._default_config)
    if relative:
      self.rel_anchor = anchor
    else:
      self.set_anchor_absolute(anchor)

  def size(self):
    return (self.img.width, self.img.height)

  def scale(self, factor, max_pixels = None):
    max_pixels = max_pixels or self.config["max_pixels"]
    w, h = self.size()
    npx = w*h*factor**2
    if npx > self.config["max_pixels"] and self.config["max_pixels"] > 0:
      raise ValueError(
        f"Scaling attempt would exceed the maximum amount of pixels ({npx} > "
        f"{max_pixels})"
      )
    new_size = (int(w*factor), int(h*factor))
    self.img = self.img.resize(new_size, self.config["resampler"])

  # computes a box for zooming in
  def _zoom_in_box(self, factor, rounding = True):
    w, h = self.size()
    ws = w/factor
    hs = h/factor
    rel_x, rel_y = self.rel_anchor
    ox = rel_x * w * (1 - 1/factor)
    oy = rel_y * h * (1 - 1/factor)
    if rounding:
      ox, oy, ws, hs = map(round, (ox, oy, ws, hs))
    corners = (ox, oy), (ox+ws, oy+hs)
    box = (ox, oy, ox+ws, oy+hs)
    return corners, box

  # computes a zoomed-in version and sets it
  def zoom_in(self, factor):
    _, box = self._zoom_in_box(factor)
    w, h = self.size()
    self.img = self.img.crop(box).resize((w, h), self.config["resampler"])

  # computes the absolute position for the anchor
  def anchor_absolute(self):
    rx, ry = self.rel_anchor
    w, h = self.size()
    return (w*rx, h*ry)

  # set an anchor by absolute position
  def set_anchor_absolute(self, p):
    x, y = p
    w, h = self.size()
    if x > w or y > h:
      return ValueError(f"Anchor {p} is out of bounds ({w}x{h})")
    self.rel_anchor = (x/w, y/h)

  # get absolute position of anchor
  def get_anchor_absolute(self):
    rx, ry = self.rel_anchor
    w, h = self.size()
    return (rx*w, ry*h)

  # paste onto this
  def paste(self, img, box = None, mask = None):
    if isinstance(img, Image.Image):
      self.img.paste(img, box, mask)
    elif isinstance(img, AnchoredImage):
      self.img.paste(img.img, box, mask)
    else:
      raise TypeError("Can only paste Image.Image or AnchoredImage")

  # paste another anchored image onto this one, so their anchors coincide
  def paste_aligned(self, img):
    ax, ay = self.get_anchor_absolute()
    bx, by = img.get_anchor_absolute()
    offset = (math.ceil(ax-bx), math.ceil(ay-by))
    self.paste(img, offset)

  # kinda meant to save time
  def save(self, *args, **kwargs):
    self.img.save(*args, **kwargs)

  # copy
  def __copy__(self):
    return AnchoredImage(self.img, self.anchor)

  # deep copy
  def __deepcopy__(self, memo):
    return AnchoredImage(self.img.copy(), self.rel_anchor)


# frame-making worker
class FrameWorker(Process):
  def __init__(self, nested_base, params, out_dir, qin, qout, num):
    self.nested_base = nested_base
    self.params = params
    self.out_dir = out_dir
    self.qin = qin
    self.qout = qout
    self.num = num
    super().__init__()

  # makes and writes a single frame
  def make_frame(self, nframe):
    zoom = self.params["inner_scale"]**(1/(self.params["num_frames"]-1))
    mz = zoom**(nframe-1)
    frame = copy.deepcopy(self.nested_base)
    frame.zoom_in(mz)
    if self.params.get("paste_within"):
      # paste an extra copy for quality
      try:
        smaller = copy.deepcopy(self.nested_base)
        smaller.scale(mz/self.params["inner_scale"])
        frame.paste_aligned(smaller)
      except ValueError:
        pass # well, at least we tried
    frame.scale(1/self.params["downscale"])
    frame.save(os.path.join(self.out_dir.name, f"frame-{nframe:05d}.png"))

  # make frames until the main process tells us to stop by sending a None
  def run(self):
    while (nframe := self.qin.get()) is not None:
      self.make_frame(nframe)
      self.qout.put(nframe)
    # signal we're done by sending a None too
    self.qout.put(None)


# this is there the magic happens
class Gifception():
  # the config thing stores values that will dictate the functioning of this
  # whole module
  _default_config = {
    "max_pixels": 8e8,
    "num_processes": 1
  }

  # the params thing stores values specific to the creation of an animation
  _default_params = {
    "preup": 2,
    "inner_scale": 4,
    "downscale": 2,
    "num_frames": 120,
    "fps": 60,
    "paste_within": True
  }

  def __init__(self, base_image, config = None, params = None):
    self.load_image(base_image)
    self.config = config or copy.copy(Gifception._default_config)
    self.params = params or copy.copy(Gifception._default_params)
    self.nested_base = None
    self.frame_workers = set()

  def load_image(self, img):
    if isinstance(img, Image.Image):
      self.base_image = AnchoredImage(imge)
    elif isinstance(img, AnchoredImage):
      self.base_image = img
    else:
      raise TypeError("Need an Image or AnchoredImage!")

  def get_anchor_relative(self):
    return self.base_image.rel_anchor

  def get_anchor_absolute(self):
    return self.base_image.get_anchor_absolute()

  def set_anchor_relative(self, pt):
    self.base_image.set_anchor_relative(pt)

  def set_anchor_absolute(self, pt):
    self.base_image.set_anchor_absolute(pt)

  # prepares the image which will be used as base for the looping-in
  def prepare_nested_base(self):
    self.nested_base = copy.deepcopy(self.base_image)
    self.nested_base.scale(self.params["preup"])
    mini = copy.deepcopy(self.base_image)
    s = 1/self.params["inner_scale"]
    mini.scale(self.params["preup"]*s)
    true_scale = s
    # paste until we liiterally cannot (Pillow raises when the image is too
    # small to further downscale)
    while True:
      try:
        self.nested_base.paste_aligned(mini)
        mini.scale(s)
        true_scale *= s
      except ValueError:
        break

  # this one makes a tempdir object, starts filling it up with frames, returns
  # the tempdir object. hey, the directory is nuked at the end of said object's
  # lifetime, so be careful with it!
  # some multithreading magic happens here too...
  def start_making_frames(self):
    if len(self.frame_workers):
      raise GifceptionException("Frame generation still in progress!")
    if self.nested_base is None:
      self.prepare_nested_base()
    td = TemporaryDirectory(prefix = "gifception_")
    nt = self.config["num_processes"]
    nf = self.params["num_frames"]
    # prepare the list of frames to be consumed
    qin_l = list(range(1, nf+1)) + [None]*nt
    self.qin, self.qout = Queue(nt + nf), Queue(nt + nf)
    for instr in qin_l:
      self.qin.put(instr)
    # prepare and start the processes
    for pn in range(1, nt+1):
      fw = FrameWorker(
        self.nested_base, self.params, td, self.qin, self.qout, pn
      )
      self.frame_workers.add(fw)
      fw.start()
    return td

  # am I making frames?
  def is_making_frames(self):
    tq = self.config["num_processes"] + self.params["num_frames"]
    return self.qout.qsize() < tq

  # wait until frames are done, raises if things go awry
  def wait_for_frames(self, timeout = None):
    if self.qin is None:
      raise GifceptionException("No frame-generating process was ever started!")
    for fw in self.frame_workers.copy():
      fw.join(timeout)
      self.frame_workers.remove(fw)
    if not self.qin.empty():
      raise GifceptionException("Not all frames were consumed!")
    tq = self.config["num_processes"] + self.params["num_frames"]
    if self.qout.qsize() != tq:
      raise GifceptionException("Not all frames were produced!")

  # generates frames and blocks until they're done
  def make_frames(self):
    td = self.start_making_frames()
    self.wait_for_frames()
    return td


def test(f = True, r = Image.BICUBIC):
  bbr_pil = Image.open("bbr.png").convert("RGBA")
  abs_anchor = (65, 64+12)
  bbr = AnchoredImage(bbr_pil, abs_anchor, False)
  test_config = {
    "max_pixels": 8e8,
    "num_processes": 5,
    "resampler": r
  }
  test_params = {
    "preup": 10,
    "inner_scale": 20,
    "downscale": 1,
    "num_frames": 120,
    "fps": 60,
    "paste_within": f
  }
  gf = Gifception(bbr, test_config, test_params)
  gf.prepare_nested_base()
  gf.nested_base.save("nested.png")
  return gf.make_frames()
