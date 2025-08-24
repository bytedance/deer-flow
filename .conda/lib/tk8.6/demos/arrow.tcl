# arrow.tcl --
#
# This demonstration script creates a canvas widget that displays a
# large line with an arrowhead whose shape can be edited interactively.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

# arrowSetup --
# This procedure regenerates all the text and graphics in the canvas
# window.  It's called when the canvas is initially created, and also
# whenever any of the parameters of the arrow head are changed
# interactively.
#
# Arguments:
# c -		Name of the canvas widget.

proc arrowSetup c {
    upvar #0 demo_arrowInfo v

    # Remember the current box, if there is one.

    set tags [$c gettags current]
    if {$tags != ""} {
	set cur [lindex $tags [lsearch -glob $tags box?]]
    } else {
	set cur ""
    }

    # Create the arrow and outline.

    $c delete all
    eval {$c create line $v(x1) $v(y) $v(x2) $v(y)  -arrow last \
	    -width [expr {10*$v(width)}] -arrowshape [list \
	    [expr {10*$v(a)}] [expr {10*$v(b)}] [expr {10*$v(c)}]]} \
	    $v(bigLineStyle)
    set xtip [expr {$v(x2)-10*$v(b)}]
    set deltaY [expr {10*$v(c)+5*$v(width)}]
    $c create line $v(x2) $v(y) $xtip [expr {$v(y)+$deltaY}] \
	    [expr {$v(x2)-10*$v(a)}] $v(y) $xtip [expr {$v(y)-$deltaY}] \
	    $v(x2) $v(y) -width 2 -capstyle round -joinstyle round

    # Create the boxes for reshaping the line and arrowhead.

    eval {$c create rect [expr {$v(x2)-10*$v(a)-5}] [expr {$v(y)-5}] \
	    [expr {$v(x2)-10*$v(a)+5}] [expr {$v(y)+5}] \
	    -tags {box1 box}} $v(boxStyle)
    eval {$c create rect [expr {$xtip-5}] [expr {$v(y)-$deltaY-5}] \
	    [expr {$xtip+5}] [expr {$v(y)-$deltaY+5}] \
	    -tags {box2 box}} $v(boxStyle)
    eval {$c create rect [expr {$v(x1)-5}] [expr {$v(y)-5*$v(width)-5}] \
	    [expr {$v(x1)+5}] [expr {$v(y)-5*$v(width)+5}] \
	    -tags {box3 box}} $v(boxStyle)
    if {$cur != ""} {
	eval $c itemconfigure $cur $v(activeStyle)
    }

    # Create three arrows in actual size with the same parameters

    $c create line [expr {$v(x2)+50}] 0 [expr {$v(x2)+50}] 1000 \
	    -width 2
    set tmp [expr {$v(x2)+100}]
    $c create line $tmp [expr {$v(y)-125}] $tmp [expr {$v(y)-75}] \
	    -width $v(width) \
	    -arrow both -arrowshape "$v(a) $v(b) $v(c)"
    $c create line [expr {$tmp-25}] $v(y) [expr {$tmp+25}] $v(y) \
	    -width $v(width) \
	    -arrow both -arrowshape "$v(a) $v(b) $v(c)"
    $c create line [expr {$tmp-25}] [expr {$v(y)+75}] [expr {$tmp+25}] \
	    [expr {$v(y)+125}] -width $v(width) \
	    -arrow both -arrowshape "$v(a) $v(b) $v(c)"

    # Create a bunch of other arrows and text items showing the
    # current dimensions.

    set tmp [expr {$v(x2)+10}]
    $c create line $tmp [expr {$v(y)-5*$v(width)}] \
	    $tmp [expr {$v(y)-$deltaY}] \
	    -arrow both -arrowshape $v(smallTips)
    $c create text [expr {$v(x2)+15}] [expr {$v(y)-$deltaY+5*$v(c)}] \
	    -text $v(c) -anchor w
    set tmp [expr {$v(x1)-10}]
    $c create line $tmp [expr {$v(y)-5*$v(width)}] \
	    $tmp [expr {$v(y)+5*$v(width)}] \
	    -arrow both -arrowshape $v(smallTips)
    $c create text [expr {$v(x1)-15}] $v(y) -text $v(width) -anchor e
    set tmp [expr {$v(y)+5*$v(width)+10*$v(c)+10}]
    $c create line [expr {$v(x2)-10*$v(a)}] $tmp $v(x2) $tmp \
	    -arrow both -arrowshape $v(smallTips)
    $c create text [expr {$v(x2)-5*$v(a)}] [expr {$tmp+5}] \
	    -text $v(a) -anchor n
    set tmp [expr {$tmp+25}]
    $c create line [expr {$v(x2)-10*$v(b)}] $tmp $v(x2) $tmp \
	    -arrow both -arrowshape $v(smallTips)
    $c create text [expr {$v(x2)-5*$v(b)}] [expr {$tmp+5}] \
	    -text $v(b) -anchor n

    $c create text $v(x1) 310 -text "-width  $v(width)" \
	    -anchor w -font {Helvetica 18}
    $c create text $v(x1) 330 -text "-arrowshape  {$v(a)  $v(b)  $v(c)}" \
	    -anchor w -font {Helvetica 18}

    incr v(count)
}

set w .arrow
catch {destroy $w}
toplevel $w
wm title $w "Arrowhead Editor Demonstration"
wm iconname $w "arrow"
positionWindow $w
set c $w.c

label $w.msg -font $font -wraplength 5i -justify left -text "This widget allows you to experiment with different widths and arrowhead shapes for lines in canvases.  To change the line width or the shape of the arrowhead, drag any of the three boxes attached to the oversized arrow.  The arrows on the right give examples at normal scale.  The text at the bottom shows the configuration options as you'd enter them for a canvas line item."
pack $w.msg -side top

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

canvas $c -width 500 -height 350 -relief sunken -borderwidth 2
pack $c -expand yes -fill both

set demo_arrowInfo(a) 8
set demo_arrowInfo(b) 10
set demo_arrowInfo(c) 3
set demo_arrowInfo(width) 2
set demo_arrowInfo(motionProc) arrowMoveNull
set demo_arrowInfo(x1) 40
set demo_arrowInfo(x2) 350
set demo_arrowInfo(y) 150
set demo_arrowInfo(smallTips) {5 5 2}
set demo_arrowInfo(count) 0
if {[winfo depth $c] > 1} {
    if {[tk windowingsystem] eq "aqua"} {
	set demo_arrowInfo(bigLineStyle) "-fill systemSelectedTextBackgroundColor"
    } else {
	set demo_arrowInfo(bigLineStyle) "-fill LightSeaGreen"
    }
    set demo_arrowInfo(boxStyle) "-fill {} -width 1"
    set demo_arrowInfo(activeStyle) "-fill red -width 1"
} else {
    # Main widget program sets variable tk_demoDirectory
    set demo_arrowInfo(bigLineStyle) "-fill black \
	-stipple @[file join $tk_demoDirectory images grey.25]"
    set demo_arrowInfo(boxStyle) "-fill {} -outline black -width 1"
    set demo_arrowInfo(activeStyle) "-fill black -outline black -width 1"
}
arrowSetup $c
$c bind box <Enter> "$c itemconfigure current $demo_arrowInfo(activeStyle)"
$c bind box <Leave> "$c itemconfigure current $demo_arrowInfo(boxStyle)"
$c bind box <B1-Enter> " "
$c bind box <B1-Leave> " "
$c bind box1 <Button-1> {set demo_arrowInfo(motionProc) arrowMove1}
$c bind box2 <Button-1> {set demo_arrowInfo(motionProc) arrowMove2}
$c bind box3 <Button-1> {set demo_arrowInfo(motionProc) arrowMove3}
$c bind box <B1-Motion> "\$demo_arrowInfo(motionProc) $c %x %y"
bind $c <ButtonRelease-1> "arrowSetup $c"

# arrowMove1 --
# This procedure is called for each mouse motion event on box1 (the
# one at the vertex of the arrow).  It updates the controlling parameters
# for the line and arrowhead.
#
# Arguments:
# c -		The name of the canvas window.
# x, y -	The coordinates of the mouse.

proc arrowMove1 {c x y} {
    upvar #0 demo_arrowInfo v
    set newA [expr {($v(x2)+5-round([$c canvasx $x]))/10}]
    if {$newA < 0} {
	set newA 0
    }
    if {$newA > 25} {
	set newA 25
    }
    if {$newA != $v(a)} {
	$c move box1 [expr {10*($v(a)-$newA)}] 0
	set v(a) $newA
    }
}

# arrowMove2 --
# This procedure is called for each mouse motion event on box2 (the
# one at the trailing tip of the arrowhead).  It updates the controlling
# parameters for the line and arrowhead.
#
# Arguments:
# c -		The name of the canvas window.
# x, y -	The coordinates of the mouse.

proc arrowMove2 {c x y} {
    upvar #0 demo_arrowInfo v
    set newB [expr {($v(x2)+5-round([$c canvasx $x]))/10}]
    if {$newB < 0} {
	set newB 0
    }
    if {$newB > 25} {
	set newB 25
    }
    set newC [expr {($v(y)+5-round([$c canvasy $y])-5*$v(width))/10}]
    if {$newC < 0} {
	set newC 0
    }
    if {$newC > 20} {
	set newC 20
    }
    if {($newB != $v(b)) || ($newC != $v(c))} {
	$c move box2 [expr {10*($v(b)-$newB)}] [expr {10*($v(c)-$newC)}]
	set v(b) $newB
	set v(c) $newC
    }
}

# arrowMove3 --
# This procedure is called for each mouse motion event on box3 (the
# one that controls the thickness of the line).  It updates the
# controlling parameters for the line and arrowhead.
#
# Arguments:
# c -		The name of the canvas window.
# x, y -	The coordinates of the mouse.

proc arrowMove3 {c x y} {
    upvar #0 demo_arrowInfo v
    set newWidth [expr {($v(y)+2-round([$c canvasy $y]))/5}]
    if {$newWidth < 0} {
	set newWidth 0
    }
    if {$newWidth > 20} {
	set newWidth 20
    }
    if {$newWidth != $v(width)} {
	$c move box3 0 [expr {5*($v(width)-$newWidth)}]
	set v(width) $newWidth
    }
}
