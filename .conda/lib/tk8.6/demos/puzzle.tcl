# puzzle.tcl --
#
# This demonstration script creates a 15-puzzle game using a collection
# of buttons.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

# puzzleSwitch --
# This procedure is invoked when the user clicks on a particular button;
# if the button is next to the empty space, it moves the button into the
# empty space.

proc puzzleSwitch {w num} {
    global xpos ypos
    if {(($ypos($num) >= ($ypos(space) - .01))
	    && ($ypos($num) <= ($ypos(space) + .01))
	    && ($xpos($num) >= ($xpos(space) - .26))
	    && ($xpos($num) <= ($xpos(space) + .26)))
	    || (($xpos($num) >= ($xpos(space) - .01))
	    && ($xpos($num) <= ($xpos(space) + .01))
	    && ($ypos($num) >= ($ypos(space) - .26))
	    && ($ypos($num) <= ($ypos(space) + .26)))} {
	set tmp $xpos(space)
	set xpos(space) $xpos($num)
	set xpos($num) $tmp
	set tmp $ypos(space)
	set ypos(space) $ypos($num)
	set ypos($num) $tmp
	place $w.frame.$num -relx $xpos($num) -rely $ypos($num)
    }
}

set w .puzzle
catch {destroy $w}
toplevel $w
wm title $w "15-Puzzle Demonstration"
wm iconname $w "15-Puzzle"
positionWindow $w

label $w.msg -font $font -wraplength 4i -justify left -text "A 15-puzzle appears below as a collection of buttons.  Click on any of the pieces next to the space, and that piece will slide over the space.  Continue this until the pieces are arranged in numerical order from upper-left to lower-right."
pack $w.msg -side top

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

# Special trick: select a darker color for the space by creating a
# scrollbar widget and using its trough color.

scrollbar $w.s

# The button metrics are a bit bigger in Aqua, and since we are
# using place which doesn't autosize, then we need to have a
# slightly larger frame here...

if {[tk windowingsystem] eq "aqua"} {
    set frameSize 168
} else {
    set frameSize 120
}

frame $w.frame -width $frameSize -height $frameSize -borderwidth 2\
	-relief sunken -bg [$w.s cget -troughcolor]
pack $w.frame -side top -pady 1c -padx 1c
destroy $w.s

set order {3 1 6 2 5 7 15 13 4 11 8 9 14 10 12}
for {set i 0} {$i < 15} {set i [expr {$i+1}]} {
    set num [lindex $order $i]
    set xpos($num) [expr {($i%4)*.25}]
    set ypos($num) [expr {($i/4)*.25}]
    button $w.frame.$num -relief raised -text $num -bd 0 -highlightthickness 0 \
	    -command "puzzleSwitch $w $num"
    place $w.frame.$num -relx $xpos($num) -rely $ypos($num) \
	-relwidth .25 -relheight .25
}
set xpos(space) .75
set ypos(space) .75
