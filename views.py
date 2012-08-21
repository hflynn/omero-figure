from django.http import Http404, HttpResponse
from django.shortcuts import render_to_response
from django.utils import simplejson
from django.conf import settings
import os
import shutil

try:
    from PIL import Image
except ImportError:
    import Image
from cStringIO import StringIO

from omeroweb.decorators import login_required


def index(request):
    """
    Just a place-holder while we get started
    """

    return HttpResponse("Welcome to weblabs!")


@login_required()
def fast_image_stack (request, imageId, conn=None, **kwargs):
    """ Load all the planes of image into viewer, so we have them all in hand for fast viewing of stack """
    
    image = conn.getObject("Image", long(imageId))
    z_indices = range(image.getSizeZ())
    return render_to_response('weblabs/image_viewers/fast_image_stack.html', {'image':image, 'z_indices':z_indices})


@login_required()
def max_intensity_indices (request, imageId, theC, conn=None, **kwargs):
    """ 
    Returns a 2D plane (same width and height as the image) where each 'pixel' value is
    the Z-index of the max intensity.
    """
    
    image = conn.getObject("Image", long(imageId))
    w = image.getSizeX()
    h = image.getSizeY()
    miPlane = [[0]*w for x in xrange(h)]
    indexPlane = [[0]*w for x in xrange(h)]
    
    pixels = image.getPrimaryPixels()
    
    c = int(theC)
    
    for z in range(image.getSizeZ()):
        plane = pixels.getPlane(z, c, 0)
        for x in range(w):
            for y in range(h):
                if plane[y][x] > miPlane[y][x]:
                    miPlane[y][x] = plane[y][x]
                    indexPlane[y][x] = z

    return HttpResponse(simplejson.dumps(indexPlane), mimetype='application/javascript')


@login_required()
def rotation_3d_viewer (request, imageId, conn=None, **kwargs):
    """ Shows an image viewer where the user can rotate the image in 3D using projections generated by ImageJ """

    image = conn.getObject("Image", long(imageId))
    default_z = image.getSizeZ() /2
    return render_to_response('weblabs/image_viewers/rotation_3d_viewer.html', {'image':image, 'default_z': default_z})


@login_required()
def rotation_proj_stitch (request, imageId, conn=None, **kwargs):
    """ 
    Use ImageJ to give 3D 'rotation projections' - stitch these into a single jpeg 
    so we can return them all as a single http response
    """

    region = request.REQUEST.get('region', None)    # x,y,w,h  option to use region of image
    axis = request.REQUEST.get('axis', 'Y')

    inimagejpath = "/Applications/ImageJ/ImageJ.app/Contents/Resources/Java/ij.jar" # Path to ij.jar
    rotation_ijm = """str=getArgument();
args=split(str,"*");
ippath=args[0];
slices=args[1];
opname=args[2];
oppath=args[3];

run("Image Sequence...", "open=&ippath number=&slices starting=1 increment=1 scale=100 file=[] or=[] sort");"""
    rotation_ijm += '\nrun("3D Project...", "projection=[Brightest Point] axis=%s-Axis slice=1 initial=0 total=360 rotation=10 lower=1 upper=255 opacity=0 surface=100 interior=50");'% axis
    rotation_ijm += '\nrun("Image Sequence... ", "format=JPEG name=[&opname] start=0 digits=4 save="+oppath );'
    
    image = conn.getObject("Image", long(imageId))
    sizeZ = image.getSizeZ()
    sizeX = image.getSizeX()
    sizeY = image.getSizeY()

    # need a directory where we can write temp files to exchage with ImageJ
    try:
        cache_dir = settings.CACHES['default']['LOCATION']
        if not os.path.exists(cache_dir):
            raise
    except:
        raise Http404("""No Cache Set. bin/omero config set omero.web.caches '{"default": {
                "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
                "LOCATION": "/var/tmp/django_cache"
            }}'""")

    rotation_dir = os.path.join(cache_dir, "rotation")
    tiff_stack = os.path.join(rotation_dir, "tiff_stack")
    destination = os.path.join(rotation_dir, "rot_rendered")
    ijm_path = os.path.join(rotation_dir, "rotation.ijm")
    try:
        os.mkdir(rotation_dir)
        os.mkdir(tiff_stack)
        os.mkdir(destination)
    except:
        pass # already exist, OK
    
    # write the macro to a known location (cache) we can pass to ImageJ
    f = open(ijm_path, 'w')
    f.write(rotation_ijm)
    f.close()
    theT = 0

    # getPlane() will either return us the region, OR the whole plane.
    if region is not None:
        x, y, w, h = region.split(",")
        def getPlane(z, t):
            rv = image.renderJpegRegion(z, t, x, y, w, h)
            if rv is not None:
                i = StringIO(rv)
                return Image.open(i)
    else:
        def getPlane(z, t):
            return image.renderImage(z, t)
        
    try:
        # Write a Z-stack to web cache
        for z in range(sizeZ):
            img_path = os.path.join(tiff_stack, "plane_%02d.tiff" % z)
            plane = getPlane(z, theT)   # get Plane (or region)
            plane.save(img_path)

        # Call ImageJ via command line, with macro ijm path & parameters
        macro_args = "*".join( [tiff_stack, str(sizeX), "rot_frame", destination])        # can't use ";" on Mac / Linu. Use "*"
        cmd = "java -jar %s -batch %s %s" % (inimagejpath, ijm_path, macro_args)
        os.system(cmd) #this calls the imagej macro and creates the 36 frames at each 10% and are then saved in the destination folder
        
        # let's stitch all the jpegs together, so they can be returned as single http response
        image_list=os.listdir(destination)
        stitch_width = plane.size[0] * len(image_list)
        stitch_height = plane.size[1]
        stiched = Image.new("RGB", (stitch_width,stitch_height), (255,255,255))
        x_pos = 0
        for i in image_list:
            img = Image.open(os.path.join(destination, i))
            stiched.paste(img, (x_pos, 0))
            x_pos += plane.size[0]
        rv = StringIO()
        stiched.save(rv, 'jpeg', quality=90)
        
    finally:
        # remove everything we've just created in the cache
        shutil.rmtree(rotation_dir)
    return HttpResponse(rv.getvalue(), mimetype='image/jpeg')


@login_required()
def render_settings (request, imageId, conn=None, **kwargs):
    """ Demo of 'render_settings' jQuery plugin - creates rendering controls for an image """

    image = conn.getObject("Image", imageId)
    default_z = image.getSizeZ() /2
    return render_to_response('weblabs/jquery_plugins/render_settings_plugin.html', {'image':image, 'default_z': default_z})



@login_required()
def viewport_test (request, imageId, conn=None, **kwargs):
    """ Just playing to learn viewport """

    image = conn.getObject("Image", imageId)
    default_z = image.getSizeZ() /2
    return render_to_response('weblabs/image_viewers/viewport_test.html', {'image':image, 'default_z': default_z})
