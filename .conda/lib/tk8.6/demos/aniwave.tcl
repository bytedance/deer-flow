# aniwave.tcl --
#
# This demonstration script illustrates how to adjust canvas item
# coordinates in a way that does something fairly similar to waveform
# display.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .aniwave
catch {destroy $w}
toplevel $w
wm title $w "Animated Wave Demonstration"
wm iconname $w "aniwave"
positionWindow $w

label $w.msg -font $font -wraplength 4i -justify left -text "This demonstration contains a canvas widget with a line item inside it. The animation routines work by adjusting the coordinates list of the line; a trace on a variable is used so updates to the variable result in a change of position of the line."
pack $w.msg -side top

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

# Create a canvas large enough to hold the wave. In fact, the wave
# sticks off both sides of the canvas to prevent visual glitches.
pack [canvas $w.c -width 300 -height 200 -background black] -padx 10 -pady 10 -expand yes

# Ensure that this this is an array
array set animationCallbacks {}

# Creates a coordinates list of a wave. This code does a very sketchy
# job and relies on Tk's line smoothing to make things look better.
set waveCoords {}
for {set x -10} {$x<=300} {incr x 5} {
    lappend waveCoords $x 100
}
lappend waveCoords $x 0 [incr x 5] 200

# Create a smoothed line and arrange for its coordinates to be the
# contents of the variable waveCoords.
$w.c create line $waveCoords -tags wave -width 1 -fill green -smooth 1
proc waveCoordsTracer {w args} {
    global waveCoords
    # Actual visual update will wait until we have finished
    # processing; Tk does that for us automatically.
    $w.c coords wave $waveCoords
}
trace add variable waveCoords write [list waveCoordsTracer $w]

# Basic motion handler. Given what direction the wave is travelling
# in, it advances the y coordinates in the coordinate-list one step in
# that direction.
proc basicMotion {} {
    global waveCoords direction
    set oc $waveCoords
    for {set i 1} {$i<[llength $oc]} {incr i 2} {
	if {$direction eq "left"} {
	    lset waveCoords $i [lindex $oc \
		    [expr {$i+2>[llength $oc] ? 1 : $i+2}]]
	} else {
	    lset waveCoords $i \
		    [lindex $oc [expr {$i-2<0 ? "end" : $i-2}]]
	}
    }
}

# Oscillation handler. This detects whether to reverse the direction
# of the wave by checking to see if the peak of the wave has moved off
# the screen (whose size we know already.)
proc reverser {} {
    global waveCoords direction
    if {[lindex $waveCoords 1] < 10} {
	set direction "right"
    } elseif {[lindex $waveCoords end] < 10} {
	set direction "left"
    }
}

# Main animation "loop". This calls the two procedures that handle the
# movement repeatedly by scheduling asynchronous calls back to itself
# using the [after] command. This procedure is the fundamental basis
# for all animated effect handling in Tk.
proc move {} {
    basicMotion
    reverser

    # Theoretically 100 frames-per-second (==10ms between frames)
    global animationCallbacks
    set animationCallbacks(simpleWave) [after 10 move]
}

# Initialise our remaining animation variables
set direction "left"
set animateAfterCallback {}
# Arrange for the animation loop to stop when the canvas is deleted
bind $w.c <Destroy> {
    after cancel $animationCallbacks(simpleWave)
    unset animationCallbacks(simpleWave)
}
# Start the animation processing
move
