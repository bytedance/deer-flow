# ruler.tcl --
#
# This demonstration script creates a canvas widget that displays a ruler
# with tab stops that can be set, moved, and deleted.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

# rulerMkTab --
# This procedure creates a new triangular polygon in a canvas to
# represent a tab stop.
#
# Arguments:
# c -		The canvas window.
# x, y -	Coordinates at which to create the tab stop.

proc rulerMkTab {c x y} {
    upvar #0 demo_rulerInfo v
    set newTab [$c create polygon $x $y \
	    [expr {$x+$v(size)}] [expr {$y+$v(size)}] \
	    [expr {$x-$v(size)}] [expr {$y+$v(size)}]]
    set fill [$c itemcget $newTab -outline]
    $c itemconfigure $newTab -fill $fill -outline {}
    set v(normalStyle) "-fill $fill"
    return $newTab
}

set w .ruler
catch {destroy $w}
toplevel $w
wm title $w "Ruler Demonstration"
wm iconname $w "ruler"
positionWindow $w
set c $w.c

label $w.msg -font $font -wraplength 5i -justify left -text "This canvas widget shows a mock-up of a ruler.  You can create tab stops by dragging them out of the well to the right of the ruler.  You can also drag existing tab stops.  If you drag a tab stop far enough up or down so that it turns dim, it will be deleted when you release the mouse button."
pack $w.msg -side top

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

canvas $c -width 14.8c -height 2.5c
pack $w.c -side top -fill x

set demo_rulerInfo(grid) .25c
set demo_rulerInfo(left) [winfo fpixels $c 1c]
set demo_rulerInfo(right) [winfo fpixels $c 13c]
set demo_rulerInfo(top) [winfo fpixels $c 1c]
set demo_rulerInfo(bottom) [winfo fpixels $c 1.5c]
set demo_rulerInfo(size) [winfo fpixels $c .2c]
# Main widget program sets variable tk_demoDirectory
if {[winfo depth $c] > 1} {
    set demo_rulerInfo(activeStyle) "-fill red -stipple {}"
    set demo_rulerInfo(deleteStyle) [list -fill red \
	    -stipple @[file join $tk_demoDirectory images gray25.xbm]]
} else {
    set demo_rulerInfo(activeStyle) "-fill black -stipple {}"
    set demo_rulerInfo(deleteStyle) [list -fill black \
	    -stipple @[file join $tk_demoDirectory images gray25.xbm]]
}

$c create line 1c 0.5c 1c 1c 13c 1c 13c 0.5c -width 1
for {set i 0} {$i < 12} {incr i} {
    set x [expr {$i+1}]
    $c create line ${x}c 1c ${x}c 0.6c -width 1
    $c create line $x.25c 1c $x.25c 0.8c -width 1
    $c create line $x.5c 1c $x.5c 0.7c -width 1
    $c create line $x.75c 1c $x.75c 0.8c -width 1
    $c create text $x.15c .75c -text $i -anchor sw
}
$c addtag well withtag [$c create rect 13.2c 1c 13.8c 0.5c \
	-fill [lindex [$c config -bg] 4]]
$c addtag well withtag [rulerMkTab $c [winfo pixels $c 13.5c] \
	[winfo pixels $c .65c]]

$c bind well <Button-1> "rulerNewTab $c %x %y"
$c bind tab <Button-1> "rulerSelectTab $c %x %y"
bind $c <B1-Motion> "rulerMoveTab $c %x %y"
bind $c <ButtonRelease-1> "rulerReleaseTab $c"

# rulerNewTab --
# Does all the work of creating a tab stop, including creating the
# triangle object and adding tags to it to give it tab behavior.
#
# Arguments:
# c -		The canvas window.
# x, y -	The coordinates of the tab stop.

proc rulerNewTab {c x y} {
    upvar #0 demo_rulerInfo v
    $c addtag active withtag [rulerMkTab $c $x $y]
    $c addtag tab withtag active
    set v(x) $x
    set v(y) $y
    rulerMoveTab $c $x $y
}

# rulerSelectTab --
# This procedure is invoked when mouse button 1 is pressed over
# a tab.  It remembers information about the tab so that it can
# be dragged interactively.
#
# Arguments:
# c -		The canvas widget.
# x, y -	The coordinates of the mouse (identifies the point by
#		which the tab was picked up for dragging).

proc rulerSelectTab {c x y} {
    upvar #0 demo_rulerInfo v
    set v(x) [$c canvasx $x $v(grid)]
    set v(y) [expr {$v(top)+2}]
    $c addtag active withtag current
    eval "$c itemconf active $v(activeStyle)"
    $c raise active
}

# rulerMoveTab --
# This procedure is invoked during mouse motion events to drag a tab.
# It adjusts the position of the tab, and changes its appearance if
# it is about to be dragged out of the ruler.
#
# Arguments:
# c -		The canvas widget.
# x, y -	The coordinates of the mouse.

proc rulerMoveTab {c x y} {
    upvar #0 demo_rulerInfo v
    if {[$c find withtag active] == ""} {
	return
    }
    set cx [$c canvasx $x $v(grid)]
    set cy [$c canvasy $y]
    if {$cx < $v(left)} {
	set cx $v(left)
    }
    if {$cx > $v(right)} {
	set cx $v(right)
    }
    if {($cy >= $v(top)) && ($cy <= $v(bottom))} {
	set cy [expr {$v(top)+2}]
	eval "$c itemconf active $v(activeStyle)"
    } else {
	set cy [expr {$cy-$v(size)-2}]
	eval "$c itemconf active $v(deleteStyle)"
    }
    $c move active [expr {$cx-$v(x)}] [expr {$cy-$v(y)}]
    set v(x) $cx
    set v(y) $cy
}

# rulerReleaseTab --
# This procedure is invoked during button release events that end
# a tab drag operation.  It deselects the tab and deletes the tab if
# it was dragged out of the ruler.
#
# Arguments:
# c -		The canvas widget.
# x, y -	The coordinates of the mouse.

proc rulerReleaseTab c {
    upvar #0 demo_rulerInfo v
    if {[$c find withtag active] == {}} {
	return
    }
    if {$v(y) != $v(top)+2} {
	$c delete active
    } else {
	eval "$c itemconf active $v(normalStyle)"
	$c dtag active
    }
}
