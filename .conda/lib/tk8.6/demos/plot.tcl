# plot.tcl --
#
# This demonstration script creates a canvas widget showing a 2-D
# plot with data points that can be dragged with the mouse.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .plot
catch {destroy $w}
toplevel $w
wm title $w "Plot Demonstration"
wm iconname $w "Plot"
positionWindow $w
set c $w.c

label $w.msg -font $font -wraplength 4i -justify left -text "This window displays a canvas widget containing a simple 2-dimensional plot.  You can doctor the data by dragging any of the points with mouse button 1."
pack $w.msg -side top

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

canvas $c -relief raised -width 450 -height 300
pack $w.c -side top -fill x

set plotFont {Helvetica 18}

$c create line 100 250 400 250 -width 2
$c create line 100 250 100 50 -width 2
$c create text 225 20 -text "A Simple Plot" -font $plotFont -fill brown

for {set i 0} {$i <= 10} {incr i} {
    set x [expr {100 + ($i*30)}]
    $c create line $x 250 $x 245 -width 2
    $c create text $x 254 -text [expr {10*$i}] -anchor n -font $plotFont
}
for {set i 0} {$i <= 5} {incr i} {
    set y [expr {250 - ($i*40)}]
    $c create line 100 $y 105 $y -width 2
    $c create text 96 $y -text [expr {$i*50}].0 -anchor e -font $plotFont
}

foreach point {
    {12 56} {20 94} {33 98} {32 120} {61 180} {75 160} {98 223}
} {
    set x [expr {100 + (3*[lindex $point 0])}]
    set y [expr {250 - (4*[lindex $point 1])/5}]
    set item [$c create oval [expr {$x-6}] [expr {$y-6}] \
	    [expr {$x+6}] [expr {$y+6}] -width 1 -outline black \
	    -fill SkyBlue2]
    $c addtag point withtag $item
}

$c bind point <Enter> "$c itemconfig current -fill red"
$c bind point <Leave> "$c itemconfig current -fill SkyBlue2"
$c bind point <Button-1> "plotDown $c %x %y"
$c bind point <ButtonRelease-1> "$c dtag selected"
bind $c <B1-Motion> "plotMove $c %x %y"

set plot(lastX) 0
set plot(lastY) 0

# plotDown --
# This procedure is invoked when the mouse is pressed over one of the
# data points.  It sets up state to allow the point to be dragged.
#
# Arguments:
# w -		The canvas window.
# x, y -	The coordinates of the mouse press.

proc plotDown {w x y} {
    global plot
    $w dtag selected
    $w addtag selected withtag current
    $w raise current
    set plot(lastX) $x
    set plot(lastY) $y
}

# plotMove --
# This procedure is invoked during mouse motion events.  It drags the
# current item.
#
# Arguments:
# w -		The canvas window.
# x, y -	The coordinates of the mouse.

proc plotMove {w x y} {
    global plot
    $w move selected [expr {$x-$plot(lastX)}] [expr {$y-$plot(lastY)}]
    set plot(lastX) $x
    set plot(lastY) $y
}
