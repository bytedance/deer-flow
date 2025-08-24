# Setup file from the pygame project

#--StartConfig
SDL = -I/usr/include/SDL -D_REENTRANT -lSDL
FONT = -lSDL_ttf
IMAGE = -lSDL_image
MIXER = -lSDL_mixer
SMPEG = -lsmpeg
PNG = -lpng
JPEG = -ljpeg
SCRAP = -lX11
PORTMIDI = -lportmidi
PORTTIME = -lporttime
#--EndConfig

#DEBUG = -C-W -C-Wall
DEBUG = 

#the following modules are optional. you will want to compile
#everything you can, but you can ignore ones you don't have
#dependencies for, just comment them out

imageext src/imageext.c $(SDL) $(IMAGE) $(PNG) $(JPEG) $(DEBUG)
font src/font.c $(SDL) $(FONT) $(DEBUG)
mixer src/mixer.c $(SDL) $(MIXER) $(DEBUG)
mixer_music src/music.c $(SDL) $(MIXER) $(DEBUG)
_numericsurfarray src/_numericsurfarray.c $(SDL) $(DEBUG)
_numericsndarray src/_numericsndarray.c $(SDL) $(MIXER) $(DEBUG)
movie src/movie.c $(SDL) $(SMPEG) $(DEBUG)
scrap src/scrap.c $(SDL) $(SCRAP) $(DEBUG)
_camera src/_camera.c src/camera_v4l2.c src/camera_v4l.c $(SDL) $(DEBUG)
pypm src/pypm.c $(SDL) $(PORTMIDI) $(PORTTIME) $(DEBUG)

GFX = src/SDL_gfx/SDL_gfxPrimitives.c 
#GFX = src/SDL_gfx/SDL_gfxBlitFunc.c src/SDL_gfx/SDL_gfxPrimitives.c 
gfxdraw src/gfxdraw.c $(SDL) $(GFX) $(DEBUG)



#these modules are required for pygame to run. they only require
#SDL as a dependency. these should not be altered

base src/base.c $(SDL) $(DEBUG)
cdrom src/cdrom.c $(SDL) $(DEBUG)
color src/color.c $(SDL) $(DEBUG)
constants src/constants.c $(SDL) $(DEBUG)
display src/display.c $(SDL) $(DEBUG)
event src/event.c $(SDL) $(DEBUG)
fastevent src/fastevent.c src/fastevents.c $(SDL) $(DEBUG)
key src/key.c $(SDL) $(DEBUG)
mouse src/mouse.c $(SDL) $(DEBUG)
rect src/rect.c $(SDL) $(DEBUG)
rwobject src/rwobject.c $(SDL) $(DEBUG)
surface src/surface.c src/alphablit.c src/surface_fill.c $(SDL) $(DEBUG)
surflock src/surflock.c $(SDL) $(DEBUG)
time src/time.c $(SDL) $(DEBUG)
joystick src/joystick.c $(SDL) $(DEBUG)
draw src/draw.c $(SDL) $(DEBUG)
image src/image.c $(SDL) $(DEBUG)
overlay src/overlay.c $(SDL) $(DEBUG)
transform src/transform.c src/rotozoom.c src/scale2x.c src/scale_mmx.c $(SDL) $(DEBUG)
mask src/mask.c src/bitmask.c $(SDL) $(DEBUG)
bufferproxy src/bufferproxy.c $(SDL) $(DEBUG)
pixelarray src/pixelarray.c $(SDL) $(DEBUG)
_arraysurfarray src/_arraysurfarray.c $(SDL) $(DEBUG)


