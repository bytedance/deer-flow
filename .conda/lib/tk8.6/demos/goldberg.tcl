##+#################################################################
#
# TkGoldberg.tcl
# by Keith Vetter, March 13, 2003
#
# "Man will always find a difficult means to perform a simple task"
# Rube Goldberg
#
# Reproduced here with permission.
#
##+#################################################################
#
# Keith Vetter 2003-03-21: this started out as a simple little program
# but was so much fun that it grew and grew. So I apologize about the
# size but I just couldn't resist sharing it.
#
# This is a whizzlet that does a Rube Goldberg type animation, the
# design of which comes from an New Years e-card from IncrediMail.
# That version had nice sound effects which I eschewed. On the other
# hand, that version was in black and white (actually dark blue and
# light blue) and this one is fully colorized.
#
# One thing I learned from this project is that drawing filled complex
# objects on a canvas is really hard. More often than not I had to
# draw each item twice--once with the desired fill color but no
# outline, and once with no fill but with the outline. Another trick
# is erasing by drawing with the background color. Having a flood fill
# command would have been extremely helpful.
#
# Two wiki pages were extremely helpful: Drawing rounded rectangles
# which I generalized into Drawing rounded polygons, and regular
# polygons which allowed me to convert ovals and arcs into polygons
# which could then be rotated (see Canvas Rotation). I also wrote
# Named Colors to aid in the color selection.
#
# I could comment on the code, but it's just 26 state machines with
# lots of canvas create and move calls.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .goldberg
catch {destroy $w}
toplevel $w
wm title $w "Tk Goldberg (demonstration)"
wm iconname $w "goldberg"
wm resizable $w 0 0
#positionWindow $w

label $w.msg -font {Arial 10} -wraplength 4i -justify left -text "This is a\
	demonstration of just how complex you can make your animations\
	become. Click the ball to start things moving!\n\n\"Man will always\
	find a difficult means to perform a simple task\"\n - Rube Goldberg"
pack $w.msg -side top

###--- End of Boilerplate ---###

# Ensure that this this is an array
array set animationCallbacks {}
bind $w <Destroy> {
    if {"%W" eq [winfo toplevel %W]} {
	unset S C speed
    }
}

set S(title) "Tk Goldberg"
set S(speed) 5
set S(cnt) 0
set S(message) "\\nWelcome\\nto\\nTcl/Tk"
array set speed {1 10 2 20 3 50 4 80 5 100 6 150 7 200 8 300 9 400 10 500}

set MSTART 0; set MGO 1; set MPAUSE 2; set MSSTEP 3; set MBSTEP 4; set MDONE 5
set S(mode) $::MSTART

# Colors for everything
set C(fg) black
set C(bg) cornflowerblue

set C(0) white;		set C(1a) darkgreen;	set C(1b) yellow
set C(2) red;		set C(3a) green;	set C(3b) darkblue
set C(4) $C(fg);	set C(5a) brown;	set C(5b) white
set C(6) magenta;	set C(7) green;		set C(8) $C(fg)
set C(9) blue4;		set C(10a) white;	set C(10b) cyan
set C(11a) yellow;	set C(11b) mediumblue;	set C(12) tan2
set C(13a) yellow;	set C(13b) red;		set C(14) white
set C(15a) green;	set C(15b) yellow;	set C(16) gray65
set C(17) \#A65353;	set C(18) $C(fg);	set C(19) gray50
set C(20) cyan;		set C(21) gray65;	set C(22) $C(20)
set C(23a) blue;	set C(23b) red;		set C(23c) yellow
set C(24a) red;		set C(24b) white;
set C(24c) black;	set C(26) $C(0);

proc DoDisplay {w} {
    global S C

    ttk::frame $w.ctrl -relief ridge -borderwidth 2 -padding 5
    pack [frame $w.screen -bd 2 -relief raised] \
	    -side left -fill both -expand 1

    canvas $w.c -width 860 -height 730 -bg $C(bg) -highlightthickness 0
    $w.c config -scrollregion {0 0 1000 1000}	;# Kludge: move everything up
    $w.c yview moveto .05
    pack $w.c -in $w.screen -side top -fill both -expand 1

    bind $w.c <Button-3> [list $w.pause invoke]
    bind $w.c <Destroy> {
	after cancel $animationCallbacks(goldberg)
	unset animationCallbacks(goldberg)
    }
    DoCtrlFrame $w
    DoDetailFrame $w
    if {[tk windowingsystem] ne "aqua"} {
	ttk::button $w.show -text "\xbb" -command [list ShowCtrl $w] -width 2
    } else {
	button $w.show -text "\xbb" -command [list ShowCtrl $w] -width 2 -highlightbackground $C(bg)
    }
    place $w.show -in $w.c -relx 1 -rely 0 -anchor ne
    update
}

proc DoCtrlFrame {w} {
    global S
    ttk::button $w.start -text "Start" -command [list DoButton $w 0]
    ttk::checkbutton $w.pause -text "Pause" -command [list DoButton $w 1] \
	    -variable S(pause)
    ttk::button $w.step -text "Single Step" -command [list DoButton $w 2]
    ttk::button $w.bstep -text "Big Step" -command [list DoButton $w 4]
    ttk::button $w.reset -text "Reset" -command [list DoButton $w 3]
    ttk::labelframe $w.details
    raise $w.details
    set S(details) 0
    ttk::checkbutton $w.details.cb -text "Details" -variable S(details)
    ttk::labelframe $w.message -text "Message"
    ttk::entry $w.message.e -textvariable S(message) -justify center
    ttk::labelframe $w.speed -text "Speed: 0"
    ttk::scale $w.speed.scale -orient horizontal -from 1 -to 10 -variable S(speed)
    ttk::button $w.about -text About -command [list About $w]

    grid $w.start -in $w.ctrl -row 0 -sticky ew
    grid rowconfigure $w.ctrl 1 -minsize 10
    grid $w.pause -in $w.ctrl -row 2 -sticky ew
    grid $w.step  -in $w.ctrl -sticky ew -pady 2
    grid $w.bstep -in $w.ctrl -sticky ew
    grid $w.reset -in $w.ctrl -sticky ew -pady 2
    grid rowconfigure $w.ctrl 10 -minsize 18
    grid $w.details -in $w.ctrl -row 11 -sticky ew
    grid rowconfigure $w.ctrl 11 -minsize 20
    $w.details configure -labelwidget $w.details.cb
    grid [ttk::frame $w.details.b -height 1]	;# Work around minor bug
    raise $w.details
    raise $w.details.cb
    grid rowconfigure $w.ctrl 50 -weight 1
    trace add variable ::S(mode) write	  [list ActiveGUI $w]
    trace add variable ::S(details) write [list ActiveGUI $w]
    trace add variable ::S(speed) write	  [list ActiveGUI $w]

    grid $w.message -in $w.ctrl -row 98 -sticky ew -pady 5
    grid $w.message.e -sticky nsew
    grid $w.speed -in $w.ctrl -row 99 -sticky ew -pady {0 5}
    pack $w.speed.scale -fill both -expand 1
    grid $w.about -in $w.ctrl -row 100 -sticky ew
    bind $w.reset <Button-3> {set S(mode) -1}		;# Debugging

    ## See Code / Dismiss buttons hack!
    set btns [addSeeDismiss $w.ctrl.buttons $w]
    grid [ttk::separator $w.ctrl.sep] -sticky ew -pady 4
    set i 0
    foreach b [winfo children $btns] {
	if {[winfo class $b] eq "TButton"} {
	    grid [set b2 [ttk::button $w.ctrl.b[incr i]]] -sticky ew
	    foreach b3 [$b configure] {
		set b3 [lindex $b3 0]
		# Some options are read-only; ignore those errors
		catch {$b2 configure $b3 [$b cget $b3]}
	    }
	}
    }
    destroy $btns
}

proc DoDetailFrame {w} {
    set w2 $w.details.f
    ttk::frame $w2

    ttk::label $w2.l -textvariable S(cnt) -background white
    grid $w2.l - - - -sticky ew -row 0
    for {set i 1} {1} {incr i} {
	if {[info procs "Move$i"] eq ""} break
	ttk::label $w2.l$i -text $i -anchor e -width 2 -background white
	ttk::label $w2.ll$i -textvariable STEP($i) -width 5 -background white
	set row [expr {($i + 1) / 2}]
	set col [expr {(($i + 1) & 1) * 2}]
	grid $w2.l$i -sticky ew -row $row -column $col
	grid $w2.ll$i -sticky ew -row $row -column [incr col]
    }
    grid columnconfigure $w2 1 -weight 1
}

# Map or unmap the ctrl window
proc ShowCtrl {w} {
    if {[winfo ismapped $w.ctrl]} {
	pack forget $w.ctrl
	$w.show config -text "\xbb"
    } else {
	pack $w.ctrl -side right -fill both -ipady 5
	$w.show config -text "\xab"
    }
}

proc DrawAll {w} {
    ResetStep
    $w.c delete all
    for {set i 0} {1} {incr i} {
	set p "Draw$i"
	if {[info procs $p] eq ""} break
	$p $w
    }
}

proc ActiveGUI {w var1 var2 op} {
    global S MGO MSTART MDONE
    array set z {0 disabled 1 normal}

    set m $S(mode)
    set S(pause) [expr {$m == 2}]
    $w.start  config -state $z([expr {$m != $MGO}])
    $w.pause  config -state $z([expr {$m != $MSTART && $m != $MDONE}])
    $w.step   config -state $z([expr {$m != $MGO && $m != $MDONE}])
    $w.bstep  config -state $z([expr {$m != $MGO && $m != $MDONE}])
    $w.reset  config -state $z([expr {$m != $MSTART}])

    if {$S(details)} {
	grid $w.details.f -sticky ew
    } else {
	grid forget $w.details.f
    }
    set S(speed) [expr {round($S(speed))}]
    $w.speed config -text "Speed: $S(speed)"
}

proc Start {} {
    global S MGO
    set S(mode) $MGO
}

proc DoButton {w what} {
    global S MDONE MGO MSSTEP MBSTEP MPAUSE

    if {$what == 0} {				;# Start
	if {$S(mode) == $MDONE} {
	    Reset $w
	}
	set S(mode) $MGO
    } elseif {$what == 1} {			;# Pause
	set S(mode) [expr {$S(pause) ? $MPAUSE : $MGO}]
    } elseif {$what == 2} {			;# Step
	set S(mode) $MSSTEP
    } elseif {$what == 3} {			;# Reset
	Reset $w
    } elseif {$what == 4} {			;# Big step
	set S(mode) $MBSTEP
    }
}

proc Go {w {who {}}} {
    global S speed animationCallbacks MGO MPAUSE MSSTEP MBSTEP

    set now [clock clicks -milliseconds]
    catch {after cancel $animationCallbacks(goldberg)}
    if {$who ne ""} {				;# Start here for debugging
	set S(active) $who
	set S(mode) $MGO
    }
    if {$S(mode) == -1} return			;# Debugging
    set n 0
    if {$S(mode) != $MPAUSE} {			;# Not paused
	set n [NextStep $w]			;# Do the next move
    }
    if {$S(mode) == $MSSTEP} {			;# Single step
	set S(mode) $MPAUSE
    }
    if {$S(mode) == $MBSTEP && $n} {		;# Big step
	set S(mode) $MSSTEP
    }

    set elapsed [expr {[clock click -milliseconds] - $now}]
    set delay [expr {$speed($S(speed)) - $elapsed}]
    if {$delay <= 0} {
	set delay 1
    }
    set animationCallbacks(goldberg) [after $delay [list Go $w]]
}

# NextStep: drives the next step of the animation
proc NextStep {w} {
    global S MSTART MDONE
    set rval 0					;# Return value

    if {$S(mode) != $MSTART && $S(mode) != $MDONE} {
	incr S(cnt)
    }
    set alive {}
    foreach {who} $S(active) {
	set n ["Move$who" $w]
	if {$n & 1} {				;# This guy still alive
	    lappend alive $who
	}
	if {$n & 2} {				;# Next guy is active
	    lappend alive [expr {$who + 1}]
	    set rval 1
	}
	if {$n & 4} {				;# End of puzzle flag
	    set S(mode) $MDONE			;# Done mode
	    set S(active) {}			;# No more animation
	    return 1
	}
    }
    set S(active) $alive
    return $rval
}
proc About {w} {
    set msg "$::S(title)\nby Keith Vetter, March 2003\n(Reproduced by kind\
	    permission of the author)\n\n\"Man will always find a difficult\
	    means to perform a simple task.\"\nRube Goldberg"
    tk_messageBox -parent $w -message $msg -title About
}
################################################################
#
# All the drawing and moving routines
#

# START HERE! banner
proc Draw0 {w} {
    set color $::C(0)
    set xy {579 119}
    $w.c create text $xy -text "START HERE!" -fill $color -anchor w \
	    -tag I0 -font {{Times Roman} 12 italic bold}
    set xy {719 119 763 119}
    $w.c create line $xy -tag I0 -fill $color -width 5 -arrow last \
	    -arrowshape {18 18 5}
    $w.c bind I0 <Button-1> Start
}
proc Move0 {w {step {}}} {
    set step [GetStep 0 $step]

    if {$::S(mode) > $::MSTART} {		;# Start the ball rolling
	MoveAbs $w I0 {-100 -100}		;# Hide the banner
	return 2
    }

    set pos {
	{673 119} {678 119} {683 119} {688 119}
	{693 119} {688 119} {683 119} {678 119}
    }
    set step [expr {$step % [llength $pos]}]
    MoveAbs $w I0 [lindex $pos $step]
    return 1
}

# Dropping ball
proc Draw1 {w} {
    set color $::C(1a)
    set color2 $::C(1b)
    set xy {844 133 800 133 800 346 820 346 820 168 844 168 844 133}
    $w.c create poly $xy -width 3 -fill $color -outline {}
    set xy {771 133 685 133 685 168 751 168 751 346 771 346 771 133}
    $w.c create poly $xy -width 3 -fill $color -outline {}

    set xy [box 812 122 9]
    $w.c create oval $xy -tag I1 -fill $color2 -outline {}
    $w.c bind I1 <Button-1> Start
}
proc Move1 {w {step {}}} {
    set step [GetStep 1 $step]
    set pos {
	{807 122} {802 122} {797 123} {793 124} {789 129} {785 153}
	{785 203} {785 278 x} {785 367} {810 392} {816 438} {821 503}
	{824 585 y} {838 587} {848 593} {857 601} {-100 -100}
    }
    if {$step >= [llength $pos]} {
	return 0
    }
    set where [lindex $pos $step]
    MoveAbs $w I1 $where

    if {[lindex $where 2] eq "y"} {
	Move15a $w
    }
    if {[lindex $where 2] eq "x"} {
	return 3
    }
    return 1
}

# Lighting the match
proc Draw2 {w} {
    set color red
    set color $::C(2)
    set xy  {750 369 740 392 760 392}		;# Fulcrum
    $w.c create poly $xy -fill $::C(fg) -outline $::C(fg)
    set xy {628 335 660 383}			;# Strike box
    $w.c create rect $xy -fill {} -outline $::C(fg)
    for {set y 0} {$y < 3} {incr y} {
	set yy [expr {335+$y*16}]
	$w.c create bitmap 628 $yy -bitmap gray25 -anchor nw \
		-foreground $::C(fg)
	$w.c create bitmap 644 $yy -bitmap gray25 -anchor nw \
		-foreground $::C(fg)
    }

    set xy {702 366 798 366}			;# Lever
    $w.c create line $xy -fill $::C(fg) -width 6 -tag I2_0
    set xy {712 363 712 355}			;# R strap
    $w.c create line $xy -fill $::C(fg) -width 3 -tag I2_1
    set xy {705 363 705 355}			;# L strap
    $w.c create line $xy -fill $::C(fg) -width 3 -tag I2_2
    set xy {679 356 679 360 717 360 717 356 679 356}	;# Match stick
    $w.c create line $xy -fill $::C(fg) -tag I2_3

    #set xy {662 352 680 365}			;# Match head
    set xy {
	671 352 677.4 353.9 680 358.5 677.4 363.1 671 365 664.6 363.1
	662 358.5 664.6 353.9
    }
    $w.c create poly $xy -fill $color -outline $color -tag I2_4
}
proc Move2 {w {step {}}} {
    set step [GetStep 2 $step]

    set stages {0 0 1 2 0 2 1 0 1 2 0 2 1}
    set xy(0) {
	686 333 692 323 682 316 674 309 671 295 668 307 662 318 662 328
	671 336
    }
    set xy(1) {687 331 698 322 703 295 680 320 668 297 663 311 661 327 671 335}
    set xy(2) {
	686 331 704 322 688 300 678 283 678 283 674 298 666 309 660 324
	672 336
    }

    if {$step >= [llength $stages]} {
	$w.c delete I2
	return 0
    }

    if {$step == 0} {				;# Rotate the match
	set beta 20
	lassign [Anchor $w I2_0 s] Ox Oy	;# Where to pivot
	for {set i 0} {[$w.c find withtag I2_$i] ne ""} {incr i} {
	    RotateItem $w I2_$i $Ox $Oy $beta
	}
	$w.c create poly -tag I2 -smooth 1 -fill $::C(2) ;# For the flame
	return 1
    }
    $w.c coords I2 $xy([lindex $stages $step])
    return [expr {$step == 7 ? 3 : 1}]
}

# Weight and pulleys
proc Draw3 {w} {
    set color $::C(3a)
    set color2 $::C(3b)

    set xy {602 296 577 174 518 174}
    foreach {x y} $xy {				;# 3 Pulleys
	$w.c create oval [box $x $y 13] -fill $color -outline $::C(fg) \
		-width 3
	$w.c create oval [box $x $y 2] -fill $::C(fg) -outline $::C(fg)
    }

    set xy {750 309 670 309}			;# Wall to flame
    $w.c create line $xy -tag I3_s -width 3 -fill $::C(fg) -smooth 1
    set xy {670 309 650 309}			;# Flame to pulley 1
    $w.c create line $xy -tag I3_0 -width 3 -fill $::C(fg)
    set xy {650 309 600 309}			;# Flame to pulley 1
    $w.c create line $xy -tag I3_1 -width 3 -fill $::C(fg)
    set xy {589 296 589 235}			;# Pulley 1 half way to 2
    $w.c create line $xy -tag I3_2 -width 3 -fill $::C(fg)
    set xy {589 235 589 174}			;# Pulley 1 other half to 2
    $w.c create line $xy -width 3 -fill $::C(fg)
    set xy {577 161 518 161}			;# Across the top
    $w.c create line $xy -width 3 -fill $::C(fg)
    set xy {505 174 505 205}			;# Down to weight
    $w.c create line $xy -tag I3_w -width 3 -fill $::C(fg)

    # Draw the weight as 2 circles, two rectangles and 1 rounded rectangle
    set xy {515 207 495 207}
    foreach {x1 y1 x2 y2} $xy {
	$w.c create oval [box $x1 $y1 6] -tag I3_ -fill $color2 \
		-outline $color2
	$w.c create oval [box $x2 $y2 6] -tag I3_ -fill $color2 \
		-outline $color2
	incr y1 -6; incr y2 6
	$w.c create rect $x1 $y1 $x2 $y2 -tag I3_ -fill $color2 \
		-outline $color2
    }
    set xy {492 220 518 263}
    set xy [RoundRect $w $xy 15]
    $w.c create poly $xy -smooth 1 -tag I3_ -fill $color2 -outline $color2
    set xy {500 217 511 217}
    $w.c create line $xy -tag I3_ -fill $color2 -width 10

    set xy {502 393 522 393 522 465}		;# Bottom weight target
    $w.c create line $xy -tag I3__ -fill $::C(fg) -join miter -width 10
}
proc Move3 {w {step {}}} {
    set step [GetStep 3 $step]

    set pos {{505 247} {505 297} {505 386.5} {505 386.5}}
    set rope(0) {750 309 729 301 711 324 690 300}
    set rope(1) {750 309 737 292 736 335 717 315 712 320}
    set rope(2) {750 309 737 309 740 343 736 351 725 340}
    set rope(3) {750 309 738 321 746 345 742 356}

    if {$step >= [llength $pos]} {
	return 0
    }

    $w.c delete "I3_$step"			;# Delete part of the rope
    MoveAbs $w I3_ [lindex $pos $step]		;# Move weight down
    $w.c coords I3_s $rope($step)		;# Flapping rope end
    $w.c coords I3_w [concat 505 174 [lindex $pos $step]]
    if {$step == 2} {
	$w.c move I3__ 0 30
	return 2
    }
    return 1
}

# Cage and door
proc Draw4 {w} {
    set color $::C(4)
    lassign {527 356 611 464} x0 y0 x1 y1

    for {set y $y0} {$y <= $y1} {incr y 12} {	;# Horizontal bars
	$w.c create line $x0 $y $x1 $y -fill $color -width 1
    }
    for {set x $x0} {$x <= $x1} {incr x 12} {	;# Vertical bars
	$w.c create line $x $y0 $x $y1 -fill $color -width 1
    }

    set xy {518 464 518 428}			;# Swing gate
    $w.c create line $xy -tag I4 -fill $color -width 3
}
proc Move4 {w {step {}}} {
    set step [GetStep 4 $step]

    set angles {-10 -20 -30 -30}
    if {$step >= [llength $angles]} {
	return 0
    }
    RotateItem $w I4 518 464 [lindex $angles $step]
    $w.c raise I4
    return [expr {$step == 3 ? 3 : 1}]
}

# Mouse
proc Draw5 {w} {
    set color $::C(5a)
    set color2 $::C(5b)
    set xy {377 248 410 248 410 465 518 465}	;# Mouse course
    lappend xy 518 428 451 428 451 212 377 212
    $w.c create poly $xy -fill $color2 -outline $::C(fg) -width 3

    set xy {
	534.5 445.5 541 440 552 436 560 436 569 440 574 446 575 452 574 454
	566 456 554 456 545 456 537 454 530 452
    }
    $w.c create poly $xy -tag {I5 I5_0} -fill $color
    set xy {573 452 592 458 601 460 613 456}	;# Tail
    $w.c create line $xy -tag {I5 I5_1} -fill $color -smooth 1 -width 3
    set xy [box 540 446 2]			;# Eye
    set xy {540 444 541 445 541 447 540 448 538 447 538 445}
    #.c create oval $xy -tag {I5 I5_2} -fill $::C(bg) -outline {}
    $w.c create poly $xy -tag {I5 I5_2} -fill $::C(bg) -outline {} -smooth 1
    set xy {538 454 535 461}			;# Front leg
    $w.c create line $xy -tag {I5 I5_3} -fill $color -width 2
    set xy {566 455 569 462}			;# Back leg
    $w.c create line $xy -tag {I5 I5_4} -fill $color -width 2
    set xy {544 455 545 460}			;# 2nd front leg
    $w.c create line $xy -tag {I5 I5_5} -fill $color -width 2
    set xy {560 455 558 460}			;# 2nd back leg
    $w.c create line $xy -tag {I5 I5_6}	 -fill $color -width 2
}
proc Move5 {w {step {}}} {
    set step [GetStep 5 $step]

    set pos {
	{553 452} {533 452} {513 452} {493 452} {473 452}
	{463 442 30} {445.5 441.5 30} {425.5 434.5 30} {422 414} {422 394}
	{422 374} {422 354} {422 334} {422 314} {422 294}
	{422 274 -30} {422 260.5 -30 x} {422.5 248.5 -28} {425 237}
    }
    if {$step >= [llength $pos]} {
	return 0
    }

    lassign [lindex $pos $step] x y beta next
    MoveAbs $w I5 [list $x $y]
    if {$beta ne ""} {
	lassign [Centroid $w I5_0] Ox Oy
	foreach id {0 1 2 3 4 5 6} {
	    RotateItem $w I5_$id $Ox $Oy $beta
	}
    }
    if {$next eq "x"} {
	return 3
    }
    return 1
}

# Dropping gumballs
array set XY6 {
    -1 {366 207} -2 {349 204} -3 {359 193} -4 {375 192} -5 {340 190}
    -6 {349 177} -7 {366 177} -8 {380 176} -9 {332 172} -10 {342 161}
    -11 {357 164} -12 {372 163} -13 {381 149} -14 {364 151} -15 {349 146}
    -16 {333 148} 0 {357 219}
    1 {359 261} 2 {359 291} 3 {359 318}	 4 {361 324}  5 {365 329}  6 {367 334}
    7 {367 340} 8 {366 346} 9 {364 350} 10 {361 355} 11 {359 370} 12 {359 391}
    13,0 {360 456}  13,1 {376 456}  13,2 {346 456}  13,3 {330 456}
    13,4 {353 444}  13,5 {368 443}  13,6 {339 442}  13,7 {359 431}
    13,8 {380 437}  13,9 {345 428}  13,10 {328 434} 13,11 {373 424}
    13,12 {331 420} 13,13 {360 417} 13,14 {345 412} 13,15 {376 410}
    13,16 {360 403}
}
proc Draw6 {w} {
    set color $::C(6)
    set xy {324 130 391 204}			;# Ball holder
    set xy [RoundRect $w $xy 10]
    $w.c create poly $xy -smooth 1 -outline $::C(fg) -width 3 -fill $color
    set xy {339 204 376 253}			;# Below the ball holder
    $w.c create rect $xy -fill {} -outline $::C(fg) -width 3 -fill $color \
	    -tag I6c
    set xy [box 346 339 28]
    $w.c create oval $xy -fill $color -outline {}	;# Rotor
    $w.c create arc $xy -outline $::C(fg) -width 2 -style arc \
	    -start 80 -extent 205
    $w.c create arc $xy -outline $::C(fg) -width 2 -style arc \
	    -start -41 -extent 85

    set xy [box 346 339 15]			;# Center of rotor
    $w.c create oval $xy -outline $::C(fg) -fill $::C(fg) -tag I6m
    set xy {352 312 352 254 368 254 368 322}	;# Top drop to rotor
    $w.c create poly $xy -fill $color -outline {}
    $w.c create line $xy -fill $::C(fg) -width 2

    set xy {353 240 367 300}			;# Poke bottom hole
    $w.c create rect $xy -fill $color -outline {}
    set xy {341 190 375 210}			;# Poke another hole
    $w.c create rect $xy -fill $color -outline {}

    set xy {368 356 368 403 389 403 389 464 320 464 320 403 352 403 352 366}
    $w.c create poly $xy -fill $color -outline {} -width 2	;# Below rotor
    $w.c create line $xy -fill $::C(fg) -width 2
    set xy [box 275 342 7]			;# On/off rotor
    $w.c create oval $xy -outline $::C(fg) -fill $::C(fg)
    set xy {276 334 342 325}			;# Fan belt top
    $w.c create line $xy -fill $::C(fg) -width 3
    set xy {276 349 342 353}			;# Fan belt bottom
    $w.c create line $xy -fill $::C(fg) -width 3

    set xy {337 212 337 247}			;# What the mouse pushes
    $w.c create line $xy -fill $::C(fg) -width 3 -tag I6_
    set xy {392 212 392 247}
    $w.c create line $xy -fill $::C(fg) -width 3 -tag I6_
    set xy {337 230 392 230}
    $w.c create line $xy -fill $::C(fg) -width 7 -tag I6_

    set who -1					;# All the balls
    set colors {red cyan orange green blue darkblue}
    lappend colors {*}$colors {*}$colors

    for {set i 0} {$i < 17} {incr i} {
	set loc [expr {-1 * $i}]
	set color [lindex $colors $i]
	$w.c create oval [box {*}$::XY6($loc) 5] -fill $color \
		-outline $color -tag I6_b$i
    }
    Draw6a $w 12				;# The wheel
}
proc Draw6a {w beta} {
    $w.c delete I6_0
    lassign {346 339} Ox Oy
    for {set i 0} {$i < 4} {incr i} {
	set b [expr {$beta + $i * 45}]
	lassign [RotateC 28 0 0 0 $b] x y
	set xy [list [expr {$Ox+$x}] [expr {$Oy+$y}] \
		[expr {$Ox-$x}] [expr {$Oy-$y}]]
	$w.c create line $xy -tag I6_0 -fill $::C(fg) -width 2
    }
}
proc Move6 {w {step {}}} {
    set step [GetStep 6 $step]
    if {$step > 62} {
	return 0
    }

    if {$step < 2} {				;# Open gate for balls to drop
	$w.c move I6_ -7 0
	if {$step == 1} {			;# Poke a hole
	    set xy {348 226 365 240}
	    $w.c create rect $xy -fill [$w.c itemcget I6c -fill] -outline {}
	}
	return 1
    }

    set s [expr {$step - 1}]			;# Do the gumball drop dance
    for {set i 0} {$i <= int(($s-1) / 3)} {incr i} {
	set tag "I6_b$i"
	if {[$w.c find withtag $tag] eq ""} break
	set loc [expr {$s - 3 * $i}]

	if {[info exists ::XY6($loc,$i)]} {
	    MoveAbs $w $tag $::XY6($loc,$i)
	} elseif {[info exists ::XY6($loc)]} {
	    MoveAbs $w $tag $::XY6($loc)
	}
    }
    if {($s % 3) == 1} {
	set first [expr {($s + 2) / 3}]
	for {set i $first} {1} {incr i} {
	    set tag "I6_b$i"
	    if {[$w.c find withtag $tag] eq ""} break
	    set loc [expr {$first - $i}]
	    MoveAbs $w $tag $::XY6($loc)
	}
    }
    if {$s >= 3} {				;# Rotate the motor
	set idx [expr {$s % 3}]
	#Draw6a $w [lindex {12 35 64} $idx]
	Draw6a $w [expr {12 + $s * 15}]
    }
    return [expr {$s == 3 ? 3 : 1}]
}

# On/off switch
proc Draw7 {w} {
    set color $::C(7)
    set xy {198 306 277 374}			;# Box
    $w.c create rect $xy -outline $::C(fg) -width 2 -fill $color -tag I7z
    $w.c lower I7z
    set xy {275 343 230 349}
    $w.c create line $xy -tag I7 -fill $::C(fg) -arrow last \
	    -arrowshape {23 23 8} -width 6
    set xy {225 324}				;# On button
    $w.c create oval [box {*}$xy 3] -fill $::C(fg) -outline $::C(fg)
    set xy {218 323}				;# On text
    set font {{Times Roman} 8}
    $w.c create text $xy -text "on" -anchor e -fill $::C(fg) -font $font
    set xy {225 350}				;# Off button
    $w.c create oval [box {*}$xy 3] -fill $::C(fg) -outline $::C(fg)
    set xy {218 349}				;# Off button
    $w.c create text $xy -text "off" -anchor e -fill $::C(fg) -font $font
}
proc Move7 {w {step {}}} {
    set step [GetStep 7 $step]
    set numsteps 30
    if {$step > $numsteps} {
	return 0
    }
    set beta [expr {30.0 / $numsteps}]
    RotateItem $w I7 275 343 $beta

    return [expr {$step == $numsteps ? 3 : 1}]
}

# Electricity to the fan
proc Draw8 {w} {
    Sine $w 271 248 271 306 5 8 -tag I8_s -fill $::C(8) -width 3
}
proc Move8 {w {step {}}} {
    set step [GetStep 8 $step]

    if {$step > 3} {
	return 0
    }
    if {$step == 0} {
	Sparkle $w [Anchor $w I8_s s] I8
	return 1

    } elseif {$step == 1} {
	MoveAbs $w I8 [Anchor $w I8_s c]
    } elseif {$step == 2} {
	MoveAbs $w I8 [Anchor $w I8_s n]
    } else {
	$w.c delete I8
    }
    return [expr {$step == 2 ? 3 : 1}]
}

# Fan
proc Draw9 {w} {
    set color $::C(9)
    set xy {266 194 310 220}
    $w.c create oval $xy -outline $color -fill $color
    set xy {280 209 296 248}
    $w.c create oval $xy -outline $color -fill $color
    set xy {288 249 252 249 260 240 280 234 296 234 316 240 324 249 288 249}
    $w.c create poly $xy -fill $color -smooth 1

    set xy {248 205 265 214 264 205 265 196}	;# Spinner
    $w.c create poly $xy -fill $color

    set xy {255 206 265 234}			;# Fan blades
    $w.c create oval $xy -fill {} -outline $::C(fg) -width 3 -tag I9_0
    set xy {255 176 265 204}
    $w.c create oval $xy -fill {} -outline $::C(fg) -width 3 -tag I9_0
    set xy {255 206 265 220}
    $w.c create oval $xy -fill {} -outline $::C(fg) -width 1 -tag I9_1
    set xy {255 190 265 204}
    $w.c create oval $xy -fill {} -outline $::C(fg) -width 1 -tag I9_1
}
proc Move9 {w {step {}}} {
    set step [GetStep 9 $step]

    if {$step & 1} {
	$w.c itemconfig I9_0 -width 4
	$w.c itemconfig I9_1 -width 1
	$w.c lower I9_1 I9_0
    } else {
	$w.c itemconfig I9_0 -width 1
	$w.c itemconfig I9_1 -width 4
	$w.c lower I9_0 I9_1
    }
    if {$step == 0} {
	return 3
    }
    return 1
}

# Boat
proc Draw10 {w} {
    set color $::C(10a)
    set color2 $::C(10b)
    set xy {191 230 233 230 233 178 191 178}	;# Sail
    $w.c create poly $xy -fill $color -width 3 -outline $::C(fg) -tag I10
    set xy [box 209 204 31]			;# Front
    $w.c create arc $xy -outline {} -fill $color -style pie \
	    -start 120 -extent 120 -tag I10
    $w.c create arc $xy -outline $::C(fg) -width 3 -style arc \
	    -start 120 -extent 120 -tag I10
    set xy [box 249 204 31]			;# Back
    $w.c create arc $xy -outline {} -fill $::C(bg) -width 3 -style pie \
	    -start 120 -extent 120 -tag I10
    $w.c create arc $xy -outline $::C(fg) -width 3 -style arc \
	    -start 120 -extent 120 -tag I10

    set xy {200 171 200 249}			;# Mast
    $w.c create line $xy -fill $::C(fg) -width 3 -tag I10
    set xy {159 234 182 234}			;# Bow sprit
    $w.c create line $xy -fill $::C(fg) -width 3 -tag I10
    set xy {180 234 180 251 220 251}		;# Hull
    $w.c create line $xy -fill $::C(fg) -width 6 -tag I10

    set xy {92 255 221 255}			;# Waves
    Sine $w {*}$xy 2 25 -fill $color2 -width 1 -tag I10w

    set xy [lrange [$w.c coords I10w] 4 end-4]	;# Water
    set xy [concat $xy 222 266 222 277 99 277]
    $w.c create poly $xy -fill $color2 -outline $color2
    set xy {222 266 222 277 97 277 97 266}	;# Water bottom
    $w.c create line $xy -fill $::C(fg) -width 3

    set xy [box 239 262 17]
    $w.c create arc $xy -outline $::C(fg) -width 3 -style arc \
	    -start 95 -extent 103
    set xy [box 76 266 21]
    $w.c create arc $xy -outline $::C(fg) -width 3 -style arc -extent 190
}
proc Move10 {w {step {}}} {
    set step [GetStep 10 $step]
    set pos {
	{195 212} {193 212} {190 212} {186 212} {181 212} {176 212}
	{171 212} {166 212} {161 212} {156 212} {151 212} {147 212} {142 212}
	{137 212} {132 212 x} {127 212} {121 212} {116 212} {111 212}
    }

    if {$step >= [llength $pos]} {
	return 0
    }
    set where [lindex $pos $step]
    MoveAbs $w I10 $where

    if {[lindex $where 2] eq "x"} {
	return 3
    }
    return 1
}

# 2nd ball drop
proc Draw11 {w} {
    set color $::C(11a)
    set color2 $::C(11b)
    set xy {23 264 55 591}			;# Color the down tube
    $w.c create rect $xy -fill $color -outline {}
    set xy [box 71 460 48]			;# Color the outer loop
    $w.c create oval $xy -fill $color -outline {}

    set xy {55 264 55 458}			;# Top right side
    $w.c create line $xy -fill $::C(fg) -width 3
    set xy {55 504 55 591}			;# Bottom right side
    $w.c create line $xy -fill $::C(fg) -width 3
    set xy [box 71 460 48]			;# Outer loop
    $w.c create arc $xy -outline $::C(fg) -width 3 -style arc \
	    -start 110 -extent -290 -tag I11i
    set xy [box 71 460 16]			;# Inner loop
    $w.c create oval $xy -outline $::C(fg) -fill {} -width 3 -tag I11i
    $w.c create oval $xy -outline $::C(fg) -fill $::C(bg) -width 3

    set xy {23 264 23 591}			;# Left side
    $w.c create line $xy -fill $::C(fg) -width 3
    set xy [box 1 266 23]			;# Top left curve
    $w.c create arc $xy -outline $::C(fg) -width 3 -style arc -extent 90

    set xy [box 75 235 9]			;# The ball
    $w.c create oval $xy -fill $color2 -outline {} -width 3 -tag I11
}
proc Move11 {w {step {}}} {
    set step [GetStep 11 $step]
    set pos {
	{75 235} {70 235} {65 237} {56 240} {46 247} {38 266} {38 296}
	{38 333} {38 399} {38 475} {74 496} {105 472} {100 437} {65 423}
	{-100 -100} {38 505} {38 527 x} {38 591}
    }

    if {$step >= [llength $pos]} {
	return 0
    }
    set where [lindex $pos $step]
    MoveAbs $w I11 $where
    if {[lindex $where 2] eq "x"} {
	return 3
    }
    return 1
}

# Hand
proc Draw12 {w} {
    set xy {20 637 20 617 20 610 20 590 40 590 40 590 60 590 60 610 60 610}
    lappend xy 60 610 65 620 60 631		;# Thumb
    lappend xy 60 631 60 637 60 662 60 669 52 669 56 669 50 669 50 662 50 637

    set y0 637					;# Bumps for fingers
    set y1 645
    for {set x 50} {$x > 20} {incr x -10} {
	set x1 [expr {$x - 5}]
	set x2 [expr {$x - 10}]
	lappend xy $x $y0 $x1 $y1 $x2 $y0
    }
    $w.c create poly $xy -fill $::C(12) -outline $::C(fg) -smooth 1 -tag I12 \
	    -width 3
}
proc Move12 {w {step {}}} {
    set step [GetStep 12 $step]
    set pos {{42.5 641 x}}
    if {$step >= [llength $pos]} {
	return 0
    }

    set where [lindex $pos $step]
    MoveAbs $w I12 $where
    if {[lindex $where 2] eq "x"} {
	return 3
    }
    return 1
}

# Fax
proc Draw13 {w} {
    set color $::C(13a)
    set xy {86 663 149 663 149 704 50 704 50 681 64 681 86 671}
    set xy2 {784 663 721 663 721 704 820 704 820 681 806 681 784 671}
    set radii {2 9 9 8 5 5 2}

    RoundPoly $w.c $xy $radii -width 3 -outline $::C(fg) -fill $color
    RoundPoly $w.c $xy2 $radii -width 3 -outline $::C(fg) -fill $color

    set xy {56 677}
    $w.c create rect [box {*}$xy 4] -fill {} -outline $::C(fg) -width 3 \
	    -tag I13
    set xy {809 677}
    $w.c create rect [box {*}$xy 4] -fill {} -outline $::C(fg) -width 3 \
	    -tag I13R

    set xy {112 687}				;# Label
    $w.c create text $xy -text "FAX" -fill $::C(fg) \
	    -font {{Times Roman} 12 bold}
    set xy {762 687}
    $w.c create text $xy -text "FAX" -fill $::C(fg) \
	    -font {{Times Roman} 12 bold}

    set xy {138 663 148 636 178 636}		;# Paper guide
    $w.c create line $xy -smooth 1 -fill $::C(fg) -width 3
    set xy {732 663 722 636 692 636}
    $w.c create line $xy -smooth 1 -fill $::C(fg) -width 3

    Sine $w 149 688 720 688 5 15 -tag I13_s -fill $::C(fg) -width 3
}
proc Move13 {w {step {}}} {
    set step [GetStep 13 $step]
    set numsteps 7

    if {$step == $numsteps+2} {
	MoveAbs $w I13_star {-100 -100}
	$w.c itemconfig I13R -fill $::C(13b) -width 2
	return 2
    }
    if {$step == 0} {				;# Button down
	$w.c delete I13
	Sparkle $w {-100 -100} I13_star		;# Create off screen
	return 1
    }
    lassign [Anchor $w I13_s w] x0 y0
    lassign [Anchor $w I13_s e] x1 y1
    set x [expr {$x0 + ($x1-$x0) * ($step - 1) / double($numsteps)}]
    MoveAbs $w I13_star [list $x $y0]
    return 1
}

# Paper in fax
proc Draw14 {w} {
    set color $::C(14)
    set xy {102 661 113 632 130 618}		;# Left paper edge
    $w.c create line $xy -smooth 1 -fill $color -width 3 -tag I14L_0
    set xy {148 629 125 640 124 662}		;# Right paper edge
    $w.c create line $xy -smooth 1 -fill $color -width 3 -tag I14L_1
    Draw14a $w L

    set xy {
	768.0 662.5 767.991316225 662.433786215 767.926187912 662.396880171
    }
    $w.c create line $xy -smooth 1 -fill $color -width 3 -tag I14R_0
    $w.c lower I14R_0
    # NB. these numbers are VERY sensitive, you must start with final size
    # and shrink down to get the values
    set xy {
	745.947897349 662.428358855 745.997829056 662.452239237 746.0 662.5
    }
    $w.c create line $xy -smooth 1 -fill $color -width 3 -tag I14R_1
    $w.c lower I14R_1
}
proc Draw14a {w side} {
    set color $::C(14)
    set xy [$w.c coords I14${side}_0]
    set xy2 [$w.c coords I14${side}_1]
    lassign $xy x0 y0 x1 y1 x2 y2
    lassign $xy2 x3 y3 x4 y4 x5 y5
    set zz [concat \
	    $x0 $y0 $x0 $y0 $xy $x2 $y2 $x2 $y2 \
	    $x3 $y3 $x3 $y3 $xy2 $x5 $y5 $x5 $y5]
    $w.c delete I14$side
    $w.c create poly $zz -tag I14$side -smooth 1 -fill $color -outline $color \
	    -width 3
    $w.c lower I14$side
}
proc Move14 {w {step {}}} {
    set step [GetStep 14 $step]

    # Paper going down
    set sc [expr {.9 - .05*$step}]
    if {$sc < .3} {
	$w.c delete I14L
	return 0
    }

    lassign [$w.c coords I14L_0] Ox Oy
    $w.c scale I14L_0 $Ox $Oy $sc $sc
    lassign [lrange [$w.c coords I14L_1] end-1 end] Ox Oy
    $w.c scale I14L_1 $Ox $Oy $sc $sc
    Draw14a $w L

    # Paper going up
    set sc [expr {.35 + .05*$step}]
    set sc [expr {1 / $sc}]

    lassign [$w.c coords I14R_0] Ox Oy
    $w.c scale I14R_0 $Ox $Oy $sc $sc
    lassign [lrange [$w.c coords I14R_1] end-1 end] Ox Oy
    $w.c scale I14R_1 $Ox $Oy $sc $sc
    Draw14a $w R

    return [expr {$step == 10 ? 3 : 1}]
}

# Light beam
proc Draw15 {w} {
    set color $::C(15a)
    set xy {824 599 824 585 820 585 829 585}
    $w.c create line $xy -fill $::C(fg) -width 3 -tag I15a
    set xy {789 599 836 643}
    $w.c create rect $xy -fill $color -outline $::C(fg) -width 3
    set xy {778 610 788 632}
    $w.c create rect $xy -fill $color -outline $::C(fg) -width 3
    set xy {766 617 776 625}
    $w.c create rect $xy -fill $color -outline $::C(fg) -width 3

    set xy {633 600 681 640}
    $w.c create rect $xy -fill $color -outline $::C(fg) -width 3
    set xy {635 567 657 599}
    $w.c create rect $xy -fill $color -outline $::C(fg) -width 2
    set xy {765 557 784 583}
    $w.c create rect $xy -fill $color -outline $::C(fg) -width 2

    Sine $w 658 580 765 580 3 15 -tag I15_s -fill $::C(fg) -width 3
}
proc Move15a {w} {
    set color $::C(15b)
    $w.c scale I15a 824 599 1 .3		;# Button down
    set xy {765 621 681 621}
    $w.c create line $xy -dash "-" -width 3 -fill $color -tag I15
}
proc Move15 {w {step {}}} {
    set step [GetStep 15 $step]
    set numsteps 6

    if {$step == $numsteps+2} {
	MoveAbs $w I15_star {-100 -100}
	return 2
    }
    if {$step == 0} {				;# Break the light beam
	Sparkle $w {-100 -100} I15_star
	set xy {765 621 745 621}
	$w.c coords I15 $xy
	return 1
    }
    lassign [Anchor $w I15_s w] x0 y0
    lassign [Anchor $w I15_s e] x1 y1
    set x [expr {$x0 + ($x1-$x0) * ($step - 1) / double($numsteps)}]
    MoveAbs $w I15_star [list $x $y0]
    return 1
}

# Bell
proc Draw16 {w} {
    set color $::C(16)
    set xy {722 485 791 556}
    $w.c create rect $xy -fill {} -outline $::C(fg) -width 3
    set xy [box 752 515 25]			;# Bell
    $w.c create oval $xy -fill $color -outline black -tag I16b -width 2
    set xy [box 752 515 5]			;# Bell button
    $w.c create oval $xy -fill black -outline black -tag I16b

    set xy {784 523 764 549}			;# Clapper
    $w.c create line $xy -width 3 -tag I16c -fill $::C(fg)
    set xy [box 784 523 4]
    $w.c create oval $xy -fill $::C(fg) -outline $::C(fg) -tag I16d
}
proc Move16 {w {step {}}} {
    set step [GetStep 16 $step]

    # Note: we never stop
    lassign {760 553} Ox Oy
    if {$step & 1} {
	set beta 12
	$w.c move I16b 3 0
    } else {
	set beta -12
	$w.c move I16b -3 0
    }
    RotateItem $w I16c $Ox $Oy $beta
    RotateItem $w I16d $Ox $Oy $beta

    return [expr {$step == 1 ? 3 : 1}]
}

# Cat
proc Draw17 {w} {
    set color $::C(17)

    set xy {584 556 722 556}
    $w.c create line $xy -fill $::C(fg) -width 3
    set xy {584 485 722 485}
    $w.c create line $xy -fill $::C(fg) -width 3

    set xy {664 523 717 549}			;# Body
    $w.c create arc $xy -outline $::C(fg) -fill $color -width 3 \
	    -style chord -start 128 -extent -260 -tag I17

    set xy {709 554 690 543}			;# Paw
    $w.c create oval $xy -outline $::C(fg) -fill $color -width 3 -tag I17
    set xy {657 544 676 555}
    $w.c create oval $xy -outline $::C(fg) -fill $color -width 3 -tag I17

    set xy [box 660 535 15]			;# Lower face
    $w.c create arc $xy -outline $::C(fg) -width 3 -style arc \
	    -start 150 -extent 240 -tag I17_
    $w.c create arc $xy -outline {} -fill $color -width 1 -style chord \
	    -start 150 -extent 240 -tag I17_
    set xy {674 529 670 513 662 521 658 521 650 513 647 529}	;# Ears
    $w.c create line $xy -fill $::C(fg) -width 3 -tag I17_
    $w.c create poly $xy -fill $color -outline {} -width 1 -tag {I17_ I17_c}
    set xy {652 542 628 539}			;# Whiskers
    $w.c create line $xy -fill $::C(fg) -width 3 -tag I17_
    set xy {652 543 632 545}
    $w.c create line $xy -fill $::C(fg) -width 3 -tag I17_
    set xy {652 546 632 552}
    $w.c create line $xy -fill $::C(fg) -width 3 -tag I17_

    set xy {668 543 687 538}
    $w.c create line $xy -fill $::C(fg) -width 3 -tag {I17_ I17w}
    set xy {668 544 688 546}
    $w.c create line $xy -fill $::C(fg) -width 3 -tag {I17_ I17w}
    set xy {668 547 688 553}
    $w.c create line $xy -fill $::C(fg) -width 3 -tag {I17_ I17w}

    set xy {649 530 654 538 659 530}		;# Left eye
    $w.c create line $xy -fill $::C(fg) -width 2 -smooth 1 -tag I17
    set xy {671 530 666 538 661 530}		;# Right eye
    $w.c create line $xy -fill $::C(fg) -width 2 -smooth 1 -tag I17
    set xy {655 543 660 551 665 543}		;# Mouth
    $w.c create line $xy -fill $::C(fg) -width 2 -smooth 1 -tag I17
}
proc Move17 {w {step {}}} {
    set step [GetStep 17 $step]

    if {$step == 0} {
	$w.c delete I17				;# Delete most of the cat
	set xy {655 543 660 535 665 543}	;# Mouth
	$w.c create line $xy -fill $::C(fg) -width 3 -smooth 1 -tag I17_
	set xy [box 654 530 4]			;# Left eye
	$w.c create oval $xy -outline $::C(fg) -width 3 -fill {} -tag I17_
	set xy [box 666 530 4]			;# Right eye
	$w.c create oval $xy -outline $::C(fg) -width 3 -fill {} -tag I17_

	$w.c move I17_ 0 -20			;# Move face up
	set xy {652 528 652 554}		;# Front leg
	$w.c create line $xy -fill $::C(fg) -width 3 -tag I17_
	set xy {670 528 670 554}		;# 2nd front leg
	$w.c create line $xy -fill $::C(fg) -width 3 -tag I17_

	set xy {
	    675 506 694 489 715 513 715 513 715 513 716 525 716 525 716 525
	    706 530 695 530 679 535 668 527 668 527 668 527 675 522 676 517
	    677 512
	}					;# Body
	$w.c create poly $xy -fill [$w.c itemcget I17_c -fill] \
		-outline $::C(fg) -width 3 -smooth 1 -tag I17_
	set xy {716 514 716 554}		;# Back leg
	$w.c create line $xy -fill $::C(fg) -width 3 -tag I17_
	set xy {694 532 694 554}		;# 2nd back leg
	$w.c create line $xy -fill $::C(fg) -width 3 -tag I17_
	set xy {715 514 718 506 719 495 716 488};# Tail
	$w.c create line $xy -fill $::C(fg) -width 3 -smooth 1 -tag I17_

	$w.c raise I17w				;# Make whiskers visible
	$w.c move I17_ -5 0			;# Move away from wall a bit
	return 2
    }
    return 0
}

# Sling shot
proc Draw18 {w} {
    set color $::C(18)
    set xy {721 506 627 506}			;# Sling hold
    $w.c create line $xy -width 4 -fill $::C(fg) -tag I18

    set xy {607 500 628 513}			;# Sling rock
    $w.c create oval $xy -fill $color -outline {} -tag I18a

    set xy {526 513 606 507 494 502}		;# Sling band
    $w.c create line $xy -fill $::C(fg) -width 4 -tag I18b
    set xy { 485 490 510 540 510 575 510 540 535 491 }	;# Sling
    $w.c create line $xy -fill $::C(fg) -width 6
}
proc Move18 {w {step {}}} {
    set step [GetStep 18 $step]

    set pos {
	{587 506} {537 506} {466 506} {376 506} {266 506 x} {136 506}
	{16 506} {-100 -100}
    }

    set b(0) {490 502 719 507 524 512}		;# Band collapsing
    set b(1) {
	491 503 524 557 563 505 559 496 546 506 551 525 553 536 538 534
	532 519 529 499
    }
    set b(2) {491 503 508 563 542 533 551 526 561 539 549 550 530 500}
    set b(3) {491 503 508 563 530 554 541 562 525 568 519 544 530 501}

    if {$step >= [llength $pos]} {
	return 0
    }

    if {$step == 0} {
	$w.c delete I18
	$w.c itemconfig I18b -smooth 1
    }
    if {[info exists b($step)]} {
	$w.c coords I18b $b($step)
    }

    set where [lindex $pos $step]
    MoveAbs $w I18a $where
    if {[lindex $where 2] eq "x"} {
	return 3
    }
    return 1
}

# Water pipe
proc Draw19 {w} {
    set color $::C(19)
    set xx {249 181 155 118  86 55 22 0}
    foreach {x1 x2} $xx {
	$w.c create rect $x1 453 $x2 467 -fill $color -outline {} -tag I19
	$w.c create line $x1 453 $x2 453 -fill $::C(fg) -width 1;# Pipe top
	$w.c create line $x1 467 $x2 467 -fill $::C(fg) -width 1;# Pipe bottom
    }
    $w.c raise I11i

    set xy [box 168 460 16]			;# Bulge by the joint
    $w.c create oval $xy -fill $color -outline {}
    $w.c create arc $xy -outline $::C(fg) -width 1 -style arc \
	    -start 21 -extent 136
    $w.c create arc $xy -outline $::C(fg) -width 1 -style arc \
	    -start -21 -extent -130

    set xy {249 447 255 473}			;# First joint 26x6
    $w.c create rect $xy -fill $color -outline $::C(fg) -width 1

    set xy [box 257 433 34]			;# Bend up
    $w.c create arc $xy -outline {} -fill $color -width 1 \
	    -style pie -start 0 -extent -91
    $w.c create arc $xy -outline $::C(fg) -width 1 \
	    -style arc -start 0 -extent -90
    set xy [box 257 433 20]
    $w.c create arc $xy -outline {} -fill $::C(bg) -width 1 \
	    -style pie -start 0 -extent -92
    $w.c create arc $xy -outline $::C(fg) -width 1 \
	    -style arc -start 0 -extent -90
    set xy [box 257 421 34]			;# Bend left
    $w.c create arc $xy -outline {} -fill $color -width 1 \
	    -style pie -start 1 -extent 91
    $w.c create arc $xy -outline $::C(fg) -width 1 \
	    -style arc -start 0 -extent 90
    set xy [box 257 421 20]
    $w.c create arc $xy -outline {} -fill $::C(bg) -width 1 \
	    -style pie -start 0 -extent 90
    $w.c create arc $xy -outline $::C(fg) -width 1 \
	    -style arc -start 0 -extent 90
    set xy [box 243 421 34]			;# Bend down
    $w.c create arc $xy -outline {} -fill $color -width 1 \
	    -style pie -start 90 -extent 90
    $w.c create arc $xy -outline $::C(fg) -width 1 \
	    -style arc -start 90 -extent 90
    set xy [box 243 421 20]
    $w.c create arc $xy -outline {} -fill $::C(bg) -width 1 \
	    -style pie -start 90 -extent 90
    $w.c create arc $xy -outline $::C(fg) -width 1 \
	    -style arc -start 90 -extent 90

    set xy {270 427 296 433}			;# 2nd joint bottom
    $w.c create rect $xy -fill $color -outline $::C(fg) -width 1
    set xy {270 421 296 427}			;# 2nd joint top
    $w.c create rect $xy -fill $color -outline $::C(fg) -width 1
    set xy {249 382 255 408}			;# Third joint right
    $w.c create rect $xy -fill $color -outline $::C(fg) -width 1
    set xy {243 382 249 408}			;# Third joint left
    $w.c create rect $xy -fill $color -outline $::C(fg) -width 1
    set xy {203 420 229 426}			;# Last joint
    $w.c create rect $xy -fill $color -outline $::C(fg) -width 1

    set xy [box 168 460 6]			;# Handle joint
    $w.c create oval $xy -fill $::C(fg) -outline {} -tag I19a
    set xy {168 460 168 512}			;# Handle bar
    $w.c create line $xy -fill $::C(fg) -width 5 -tag I19b
}
proc Move19 {w {step {}}} {
    set step [GetStep 19 $step]

    set angles {30 30 30}
    if {$step == [llength $angles]} {
	return 2
    }

    RotateItem $w I19b {*}[Centroid $w I19a] [lindex $angles $step]
    return 1
}

# Water pouring
proc Draw20 {w} {
}
proc Move20 {w {step {}}} {
    set step [GetStep 20 $step]

    set pos {451 462 473 484 496 504 513 523 532}
    set freq {20 40   40  40  40  40  40  40  40}
    set pos {
	{451 20} {462 40} {473 40} {484 40} {496 40} {504 40} {513 40}
	{523 40} {532 40 x}
    }
    if {$step >= [llength $pos]} {
	return 0
    }

    $w.c delete I20
    set where [lindex $pos $step]
    lassign $where y f
    H2O $w $y $f
    if {[lindex $where 2] eq "x"} {
	return 3
    }
    return 1
}
proc H2O {w y f} {
    set color $::C(20)
    $w.c delete I20

    Sine $w 208 428 208 $y 4 $f -tag {I20 I20s} -width 3 -fill $color \
	    -smooth 1
    $w.c create line [$w.c coords I20s] -width 3 -fill $color -smooth 1 \
	    -tag {I20 I20a}
    $w.c create line [$w.c coords I20s] -width 3 -fill $color -smooth 1 \
	    -tag {I20 I20b}
    $w.c move I20a 8 0
    $w.c move I20b 16 0
}

# Bucket
proc Draw21 {w} {
    set color $::C(21)
    set xy {217 451 244 490}			;# Right handle
    $w.c create line $xy -fill $::C(fg) -width 2 -tag I21_a
    set xy {201 467 182 490}			;# Left handle
    $w.c create line $xy -fill $::C(fg) -width 2 -tag I21_a

    set xy {245 490 237 535}			;# Right side
    set xy2 {189 535 181 490}			;# Left side
    $w.c create poly [concat $xy $xy2] -fill $color -outline {} \
	    -tag {I21 I21f}
    $w.c create line $xy -fill $::C(fg) -width 2 -tag I21
    $w.c create line $xy2 -fill $::C(fg) -width 2 -tag I21

    set xy {182 486 244 498}			;# Top
    $w.c create oval $xy -fill $color -outline {} -width 2 -tag {I21 I21f}
    $w.c create oval $xy -fill {} -outline $::C(fg) -width 2 -tag {I21 I21t}
    set xy {189 532 237 540}			;# Bottom
    $w.c create oval $xy -fill $color -outline $::C(fg) -width 2 \
	    -tag {I21 I21b}
}
proc Move21 {w {step {}}} {
    set step [GetStep 21 $step]

    set numsteps 30
    if {$step  >= $numsteps} {
	return 0
    }

    lassign [$w.c coords I21b] x1 y1 x2 y2
    #lassign [$w.c coords I21t] X1 Y1 X2 Y2
    lassign {183 492 243 504} X1 Y1 X2 Y2

    set f [expr {$step / double($numsteps)}]
    set y2 [expr {$y2 - 3}]
    set xx1 [expr {$x1 + ($X1 - $x1) * $f}]
    set yy1 [expr {$y1 + ($Y1 - $y1) * $f}]
    set xx2 [expr {$x2 + ($X2 - $x2) * $f}]
    set yy2 [expr {$y2 + ($Y2 - $y2) * $f}]
    #H2O $w $yy1 40

    $w.c itemconfig I21b -fill $::C(20)
    $w.c delete I21w
    $w.c create poly $x2 $y2 $x1 $y1 $xx1 $yy1 $xx2 $yy1 -tag {I21 I21w} \
	    -outline {} -fill $::C(20)
    $w.c lower I21w I21
    $w.c raise I21b
    $w.c lower I21f

    return [expr {$step == $numsteps-1 ? 3 : 1}]
}

# Bucket drop
proc Draw22 {w} {
}
proc Move22 {w {step {}}} {
    set step [GetStep 22 $step]
    set pos {{213 513} {213 523} {213 543 x} {213 583} {213 593}}

    if {$step == 0} {$w.c itemconfig I21f -fill $::C(22)}
    if {$step >= [llength $pos]} {
	return 0
    }
    set where [lindex $pos $step]
    MoveAbs $w I21 $where
    H2O $w [lindex $where 1] 40
    $w.c delete I21_a				;# Delete handles

    if {[lindex $where 2] eq "x"} {
	return 3
    }
    return 1
}

# Blow dart
proc Draw23 {w} {
    set color  $::C(23a)
    set color2 $::C(23b)
    set color3 $::C(23c)

    set xy {185 623 253 650}			;# Block
    $w.c create rect $xy -fill black -outline $::C(fg) -width 2 -tag I23a
    set xy {187 592 241 623}			;# Balloon
    $w.c create oval $xy -outline {} -fill $color -tag I23b
    $w.c create arc $xy -outline $::C(fg) -width 3 -tag I23b \
	    -style arc -start 12 -extent 336
    set xy {239 604  258 589 258 625 239 610}	;# Balloon nozzle
    $w.c create poly $xy -outline {} -fill $color -tag I23b
    $w.c create line $xy -fill $::C(fg) -width 3 -tag I23b

    set xy {285 611 250 603}			;# Dart body
    $w.c create oval $xy -fill $color2 -outline $::C(fg) -width 3 -tag I23d
    set xy {249 596 249 618 264 607 249 596}	;# Dart tail
    $w.c create poly $xy -fill $color3 -outline $::C(fg) -width 3 -tag I23d
    set xy {249 607 268 607}			;# Dart detail
    $w.c create line $xy -fill $::C(fg) -width 3 -tag I23d
    set xy {285 607 305 607}			;# Dart needle
    $w.c create line $xy -fill $::C(fg) -width 3 -tag I23d
}
proc Move23 {w {step {}}} {
    set step [GetStep 23 $step]

    set pos {
	{277 607} {287 607} {307 607 x} {347 607} {407 607} {487 607}
	{587 607} {687 607} {787 607} {-100 -100}
    }

    if {$step >= [llength $pos]} {
	return 0
    }
    if {$step <= 1} {
	$w.c scale I23b {*}[Anchor $w I23a n] .9 .5
    }
    set where [lindex $pos $step]
    MoveAbs $w I23d $where

    if {[lindex $where 2] eq "x"} {
	return 3
    }
    return 1
}

# Balloon
proc Draw24 {w} {
    set color $::C(24a)
    set xy {366 518 462 665}			;# Balloon
    $w.c create oval $xy -fill $color -outline $::C(fg) -width 3 -tag I24
    set xy {414 666 414 729}			;# String
    $w.c create line $xy -fill $::C(fg) -width 3 -tag I24
    set xy {410 666 404 673 422 673 418 666}	;# Nozzle
    $w.c create poly $xy -fill $color -outline $::C(fg) -width 3 -tag I24

    set xy {387 567 390 549 404 542}		;# Reflections
    $w.c create line $xy -fill $::C(fg) -smooth 1 -width 2 -tag I24
    set xy {395 568 399 554 413 547}
    $w.c create line $xy -fill $::C(fg) -smooth 1 -width 2 -tag I24
    set xy {403 570 396 555 381 553}
    $w.c create line $xy -fill $::C(fg) -smooth 1 -width 2 -tag I24
    set xy {408 564 402 547 386 545}
    $w.c create line $xy -fill $::C(fg) -smooth 1 -width 2 -tag I24
}
proc Move24 {w {step {}}} {
    global S
    set step [GetStep 24 $step]

    if {$step > 4} {
	return 0
    } elseif {$step == 4} {
	return 2
    }

    if {$step == 0} {
	$w.c delete I24				;# Exploding balloon
	set xy {
	    347 465 361 557 271 503 272 503 342 574 259 594 259 593 362 626
	    320 737 320 740 398 691 436 738 436 739 476 679 528 701 527 702
	    494 627 548 613 548 613 480 574 577 473 577 473 474 538 445 508
	    431 441 431 440 400 502 347 465 347 465
	}
	$w.c create poly $xy -tag I24 -fill $::C(24b) -outline $::C(24a) \
		-width 10 -smooth 1
	set msg [subst $S(message)]
	$w.c create text [Centroid $w I24] -text $msg -tag {I24 I24t} \
		-fill $::C(24c) \
		-justify center -font {{Times Roman} 18 bold}
	return 1
    }

    $w.c itemconfig I24t -font [list {Times Roman} [expr {18 + 6*$step}] bold]
    $w.c move I24 0 -60
    $w.c scale I24 {*}[Centroid $w I24] 1.25 1.25
    return 1
}

# Displaying the message
proc Move25 {w {step {}}} {
    global S
    set step [GetStep 25 $step]
    if {$step == 0} {
	set ::XY(25) [clock clicks -milliseconds]
	return 1
    }
    set elapsed [expr {[clock clicks -milliseconds] - $::XY(25)}]
    if {$elapsed < 5000} {
	return 1
    }
    return 2
}

# Collapsing balloon
proc Move26 {w {step {}}} {
    global S
    set step [GetStep 26 $step]

    if {$step >= 3} {
	$w.c delete I24 I26
	$w.c create text 430 755 -anchor s -tag I26 \
		-fill $::C(26) \
		-text "click to continue" -font {{Times Roman} 24 bold}
	bind $w.c <Button-1> [list Reset $w]
	return 4
    }

    $w.c scale I24 {*}[Centroid $w I24] .8 .8
    $w.c move I24 0 60
    $w.c itemconfig I24t -font [list {Times Roman} [expr {30 - 6*$step}] bold]
    return 1
}

################################################################
#
# Helper functions
#

proc box {x y r} {
    return [list [expr {$x-$r}] [expr {$y-$r}] [expr {$x+$r}] [expr {$y+$r}]]
}

proc MoveAbs {w item xy} {
    lassign $xy x y
    lassign [Centroid $w $item] Ox Oy
    set dx [expr {$x - $Ox}]
    set dy [expr {$y - $Oy}]
    $w.c move $item $dx $dy
}

proc RotateItem {w item Ox Oy beta} {
    set xy [$w.c coords $item]
    set xy2 {}
    foreach {x y} $xy {
	lappend xy2 {*}[RotateC $x $y $Ox $Oy $beta]
    }
    $w.c coords $item $xy2
}

proc RotateC {x y Ox Oy beta} {
    # rotates vector (Ox,Oy)->(x,y) by beta degrees clockwise

    set x [expr {$x - $Ox}]			;# Shift to origin
    set y [expr {$y - $Oy}]

    set beta [expr {$beta * atan(1) * 4 / 180.0}]	;# Radians
    set xx [expr {$x * cos($beta) - $y * sin($beta)}]	;# Rotate
    set yy [expr {$x * sin($beta) + $y * cos($beta)}]

    set xx [expr {$xx + $Ox}]			;# Shift back
    set yy [expr {$yy + $Oy}]

    return [list $xx $yy]
}

proc Reset {w} {
    global S
    DrawAll $w
    bind $w.c <Button-1> {}
    set S(mode) $::MSTART
    set S(active) 0
}

# Each Move## keeps its state info in STEP, this retrieves and increments it
proc GetStep {who step} {
    global STEP
    if {$step ne ""} {
	set STEP($who) $step
    } elseif {![info exists STEP($who)] || $STEP($who) eq ""} {
	set STEP($who) 0
    } else {
	incr STEP($who)
    }
    return $STEP($who)
}

proc ResetStep {} {
    global STEP
    set ::S(cnt) 0
    foreach a [array names STEP] {
	set STEP($a) ""
    }
}

proc Sine {w x0 y0 x1 y1 amp freq args} {
    set PI [expr {4 * atan(1)}]
    set step 2
    set xy {}
    if {$y0 == $y1} {				;# Horizontal
	for {set x $x0} {$x <= $x1} {incr x $step} {
	    set beta [expr {($x - $x0) * 2 * $PI / $freq}]
	    set y [expr {$y0 + $amp * sin($beta)}]
	    lappend xy $x $y
	}
    } else {
	for {set y $y0} {$y <= $y1} {incr y $step} {
	    set beta [expr {($y - $y0) * 2 * $PI / $freq}]
	    set x [expr {$x0 + $amp * sin($beta)}]
	    lappend xy $x $y
	}
    }
    return [$w.c create line $xy {*}$args]
}

proc RoundRect {w xy radius args} {
    lassign $xy x0 y0 x3 y3
    set r [winfo pixels $w.c $radius]
    set d [expr {2 * $r}]

    # Make sure that the radius of the curve is less than 3/8 size of the box!
    set maxr 0.75
    if {$d > $maxr * ($x3 - $x0)} {
	set d [expr {$maxr * ($x3 - $x0)}]
    }
    if {$d > $maxr * ($y3 - $y0)} {
	set d [expr {$maxr * ($y3 - $y0)}]
    }

    set x1 [expr { $x0 + $d }]
    set x2 [expr { $x3 - $d }]
    set y1 [expr { $y0 + $d }]
    set y2 [expr { $y3 - $d }]

    set xy [list $x0 $y0 $x1 $y0 $x2 $y0 $x3 $y0 $x3 $y1 $x3 $y2]
    lappend xy $x3 $y3 $x2 $y3 $x1 $y3 $x0 $y3 $x0 $y2 $x0 $y1
    return $xy
}

proc RoundPoly {canv xy radii args} {
    set lenXY [llength $xy]
    set lenR [llength $radii]
    if {$lenXY != 2*$lenR} {
	error "wrong number of vertices and radii"
    }

    set knots {}
    lassign [lrange $xy end-1 end] x0 y0
    lassign $xy x1 y1
    lappend xy {*}[lrange $xy 0 1]

    for {set i 0} {$i < $lenXY} {incr i 2} {
	set radius [lindex $radii [expr {$i/2}]]
	set r [winfo pixels $canv $radius]

	lassign [lrange $xy [expr {$i + 2}] [expr {$i + 3}]] x2 y2
	set z [_RoundPoly2 $x0 $y0 $x1 $y1 $x2 $y2 $r]
	lappend knots {*}$z

	lassign [list $x1 $y1] x0 y0
	lassign [list $x2 $y2] x1 y1
    }
    set n [$canv create polygon $knots -smooth 1 {*}$args]
    return $n
}

proc _RoundPoly2 {x0 y0 x1 y1 x2 y2 radius} {
    set d [expr {2 * $radius}]
    set maxr 0.75

    set v1x [expr {$x0 - $x1}]
    set v1y [expr {$y0 - $y1}]
    set v2x [expr {$x2 - $x1}]
    set v2y [expr {$y2 - $y1}]

    set vlen1 [expr {sqrt($v1x*$v1x + $v1y*$v1y)}]
    set vlen2 [expr {sqrt($v2x*$v2x + $v2y*$v2y)}]
    if {$d > $maxr * $vlen1} {
	set d [expr {$maxr * $vlen1}]
    }
    if {$d > $maxr * $vlen2} {
	set d [expr {$maxr * $vlen2}]
    }

    lappend xy [expr {$x1 + $d * $v1x/$vlen1}] [expr {$y1 + $d * $v1y/$vlen1}]
    lappend xy $x1 $y1
    lappend xy [expr {$x1 + $d * $v2x/$vlen2}] [expr {$y1 + $d * $v2y/$vlen2}]

    return $xy
}

proc Sparkle {w Oxy tag} {
    set xy {299 283 298 302 295 314 271 331 239 310 242 292 256 274 281 273}
    foreach {x y} $xy {
	$w.c create line 271 304 $x $y -fill white -width 3 -tag $tag
    }
    MoveAbs $w $tag $Oxy
}

proc Centroid {w item} {
    return [Anchor $w $item c]
}

proc Anchor {w item where} {
    lassign [$w.c bbox $item] x1 y1 x2 y2
    if {[string match *n* $where]} {
	set y $y1
    } elseif {[string match *s* $where]} {
	set y $y2
    } else {
	set y [expr {($y1 + $y2) / 2.0}]
    }
    if {[string match *w* $where]} {
	set x $x1
    } elseif {[string match *e* $where]} {
	set x $x2
    } else {
	set x [expr {($x1 + $x2) / 2.0}]
    }
    return [list $x $y]
}

DoDisplay $w
Reset $w
Go $w						;# Start everything going
