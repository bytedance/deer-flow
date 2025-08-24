# pendulum.tcl --
#
# This demonstration illustrates how Tcl/Tk can be used to construct
# simulations of physical systems.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .pendulum
catch {destroy $w}
toplevel $w
wm title $w "Pendulum Animation Demonstration"
wm iconname $w "pendulum"
positionWindow $w

label $w.msg -font $font -wraplength 4i -justify left -text "This demonstration shows how Tcl/Tk can be used to carry out animations that are linked to simulations of physical systems. In the left canvas is a graphical representation of the physical system itself, a simple pendulum, and in the right canvas is a graph of the phase space of the system, which is a plot of the angle (relative to the vertical) against the angular velocity. The pendulum bob may be repositioned by clicking and dragging anywhere on the left canvas."
pack $w.msg

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

# Create some structural widgets
pack [panedwindow $w.p] -fill both -expand 1
$w.p add [labelframe $w.p.l1 -text "Pendulum Simulation"]
$w.p add [labelframe $w.p.l2 -text "Phase Space"]

# Create the canvas containing the graphical representation of the
# simulated system.
canvas $w.c -width 320 -height 200 -background white -bd 2 -relief sunken
$w.c create text 5 5 -anchor nw -text "Click to Adjust Bob Start Position"
# Coordinates of these items don't matter; they will be set properly below
$w.c create line 0 25 320 25   -tags plate -fill grey50 -width 2
$w.c create oval 155 20 165 30 -tags pivot -fill grey50 -outline {}
$w.c create line 1 1 1 1       -tags rod   -fill black  -width 3
$w.c create oval 1 1 2 2       -tags bob   -fill yellow -outline black
pack $w.c -in $w.p.l1 -fill both -expand true

# Create the canvas containing the phase space graph; this consists of
# a line that gets gradually paler as it ages, which is an extremely
# effective visual trick.
canvas $w.k -width 320 -height 200 -background white -bd 2 -relief sunken
$w.k create line 160 200 160 0 -fill grey75 -arrow last -tags y_axis
$w.k create line 0 100 320 100 -fill grey75 -arrow last -tags x_axis
for {set i 90} {$i>=0} {incr i -10} {
    # Coordinates of these items don't matter; they will be set properly below
    $w.k create line 0 0 1 1 -smooth true -tags graph$i -fill grey$i
}

$w.k create text 0 0 -anchor ne -text "\u03b8" -tags label_theta
$w.k create text 0 0 -anchor ne -text "\u03b4\u03b8" -tags label_dtheta
pack $w.k -in $w.p.l2 -fill both -expand true

# Initialize some variables
set points {}
set Theta   45.0
set dTheta   0.0
set pi       3.1415926535897933
set length 150
set home   160

# This procedure makes the pendulum appear at the correct place on the
# canvas. If the additional arguments "at $x $y" are passed (the 'at'
# is really just syntactic sugar) instead of computing the position of
# the pendulum from the length of the pendulum rod and its angle, the
# length and angle are computed in reverse from the given location
# (which is taken to be the centre of the pendulum bob.)
proc showPendulum {canvas {at {}} {x {}} {y {}}} {
    global Theta dTheta pi length home
    if {$at eq "at" && ($x!=$home || $y!=25)} {
	set dTheta 0.0
	set x2 [expr {$x - $home}]
	set y2 [expr {$y - 25}]
	set length [expr {hypot($x2, $y2)}]
	set Theta  [expr {atan2($x2, $y2) * 180/$pi}]
    } else {
	set angle [expr {$Theta * $pi/180}]
	set x [expr {$home + $length*sin($angle)}]
	set y [expr {25    + $length*cos($angle)}]
    }
    $canvas coords rod $home 25 $x $y
    $canvas coords bob [expr {$x - 15}] [expr {$y - 15}] \
	    [expr {$x + 15}] [expr {$y + 15}]
}
showPendulum $w.c

# Update the phase-space graph according to the current angle and the
# rate at which the angle is changing (the first derivative with
# respect to time.)
proc showPhase {canvas} {
    global Theta dTheta points psw psh
    lappend points [expr {$Theta + $psw}] [expr {-20*$dTheta + $psh}]
    if {[llength $points] > 100} {
    	 set points [lrange $points end-99 end]
    }
    for {set i 0} {$i<100} {incr i 10} {
	set list [lrange $points end-[expr {$i-1}] end-[expr {$i-12}]]
	if {[llength $list] >= 4} {
	    $canvas coords graph$i $list
	}
    }
}

# Set up some bindings on the canvases.  Note that when the user
# clicks we stop the animation until they release the mouse
# button. Also note that both canvases are sensitive to <Configure>
# events, which allows them to find out when they have been resized by
# the user.
bind $w.c <Destroy> {
    after cancel $animationCallbacks(pendulum)
    unset animationCallbacks(pendulum)
}
bind $w.c <Button-1> {
    after cancel $animationCallbacks(pendulum)
    showPendulum %W at %x %y
}
bind $w.c <B1-Motion> {
    showPendulum %W at %x %y
}
bind $w.c <ButtonRelease-1> {
    showPendulum %W at %x %y
    set animationCallbacks(pendulum) [after 15 repeat [winfo toplevel %W]]
}
bind $w.c <Configure> {
    %W coords plate 0 25 %w 25
    set home [expr {%w/2}]
    %W coords pivot [expr {$home - 5}] 20 [expr {$home + 5}] 30
}
bind $w.k <Configure> {
    set psh [expr {%h/2}]
    set psw [expr {%w/2}]
    %W coords x_axis 2 $psh [expr {%w - 2}] $psh
    %W coords y_axis $psw [expr {%h - 2}] $psw 2
    %W coords label_dtheta [expr {$psw - 4}] 6
    %W coords label_theta [expr {%w - 6}] [expr {$psh + 4}]
}

# This procedure is the "business" part of the simulation that does
# simple numerical integration of the formula for a simple rotational
# pendulum.
proc recomputeAngle {} {
    global Theta dTheta pi length
    set scaling [expr {3000.0/$length/$length}]

    # To estimate the integration accurately, we really need to
    # compute the end-point of our time-step.  But to do *that*, we
    # need to estimate the integration accurately!  So we try this
    # technique, which is inaccurate, but better than doing it in a
    # single step.  What we really want is bound up in the
    # differential equation:
    #       ..             - sin theta
    #      theta + theta = -----------
    #                         length
    # But my math skills are not good enough to solve this!

    # first estimate
    set firstDDTheta [expr {-sin($Theta * $pi/180)*$scaling}]
    set midDTheta [expr {$dTheta + $firstDDTheta}]
    set midTheta [expr {$Theta + ($dTheta + $midDTheta)/2}]
    # second estimate
    set midDDTheta [expr {-sin($midTheta * $pi/180)*$scaling}]
    set midDTheta [expr {$dTheta + ($firstDDTheta + $midDDTheta)/2}]
    set midTheta [expr {$Theta + ($dTheta + $midDTheta)/2}]
    # Now we do a double-estimate approach for getting the final value
    # first estimate
    set midDDTheta [expr {-sin($midTheta * $pi/180)*$scaling}]
    set lastDTheta [expr {$midDTheta + $midDDTheta}]
    set lastTheta [expr {$midTheta + ($midDTheta + $lastDTheta)/2}]
    # second estimate
    set lastDDTheta [expr {-sin($lastTheta * $pi/180)*$scaling}]
    set lastDTheta [expr {$midDTheta + ($midDDTheta + $lastDDTheta)/2}]
    set lastTheta [expr {$midTheta + ($midDTheta + $lastDTheta)/2}]
    # Now put the values back in our globals
    set dTheta $lastDTheta
    set Theta $lastTheta
}

# This method ties together the simulation engine and the graphical
# display code that visualizes it.
proc repeat w {
    global animationCallbacks

    # Simulate
    recomputeAngle

    # Update the display
    showPendulum $w.c
    showPhase $w.k

    # Reschedule ourselves
    set animationCallbacks(pendulum) [after 15 [list repeat $w]]
}
# Start the simulation after a short pause
set animationCallbacks(pendulum) [after 500 [list repeat $w]]
