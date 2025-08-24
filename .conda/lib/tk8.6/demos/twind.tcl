# twind.tcl --
#
# This demonstration script creates a text widget with a bunch of
# embedded windows.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

# Make an Aqua button's fill color match its parent's background
proc blend {bt} {
    if {[tk windowingsystem] eq "aqua"} {
	$bt configure -highlightbackground [[winfo parent $bt] cget -background]
    }
    return $bt
}

set w .twind
catch {destroy $w}
toplevel $w
wm title $w "Text Demonstration - Embedded Windows and Other Features"
wm iconname $w "Embedded Windows"
positionWindow $w

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

frame $w.f -highlightthickness 1 -borderwidth 1 -relief sunken
set t $w.f.text
text $t -yscrollcommand "$w.scroll set" -setgrid true -font $font -width 70 \
	-height 35 -wrap word -highlightthickness 0 -borderwidth 0
pack $t -expand  yes -fill both
ttk::scrollbar $w.scroll -command "$t yview"
pack $w.scroll -side right -fill y
panedwindow $w.pane
pack $w.pane -expand yes -fill both
$w.pane add $w.f
# Import to raise given creation order above
raise $w.f

$t tag configure center -justify center -spacing1 5m -spacing3 5m
$t tag configure buttons -lmargin1 1c -lmargin2 1c -rmargin 1c \
	-spacing1 3m -spacing2 0 -spacing3 0

button $t.on -text "Turn On" -command "textWindOn $w" \
	-cursor top_left_arrow
button $t.off -text "Turn Off" -command "textWindOff $w" \
	-cursor top_left_arrow

$t insert end "A text widget can contain many different kinds of items, "
$t insert end "both active and passive.  It can lay these out in various "
$t insert end "ways, with wrapping, tabs, centering, etc.  In addition, "
$t insert end "when the contents are too big for the window, smooth "
$t insert end "scrolling in all directions is provided.\n\n"

$t insert end "A text widget can contain other widgets embedded "
$t insert end "it.  These are called \"embedded windows\", "
$t insert end "and they can consist of arbitrary widgets.  "
$t insert end "For example, here are two embedded button "
$t insert end "widgets.  You can click on the first button to "
$t window create end -window [blend $t.on]
$t insert end " horizontal scrolling, which also turns off "
$t insert end "word wrapping.  Or, you can click on the second "
$t insert end "button to\n"
$t window create end -window [blend $t.off]
$t insert end " horizontal scrolling and turn back on word wrapping.\n\n"

$t insert end "Or, here is another example.  If you "
$t window create end -create {
    button %W.click -text "Click Here" -command "textWindPlot %W" \
	-cursor top_left_arrow
    blend %W.click
}

$t insert end " a canvas displaying an x-y plot will appear right here."
$t mark set plot insert
$t mark gravity plot left
$t insert end "  You can drag the data points around with the mouse, "
$t insert end "or you can click here to "
$t window create end -create {
    button %W.delete -text "Delete" -command "textWindDel %W" \
	-cursor top_left_arrow
    blend %W.delete
}
$t insert end " the plot again.\n\n"

$t insert end "You can also create multiple text widgets each of which "
$t insert end "display the same underlying text. Click this button to "
$t window create end \
  -create {button %W.peer -text "Make A Peer" -command "textMakePeer %W" \
	       -cursor top_left_arrow
      blend %W.peer} -padx 3
$t insert end " widget.  Notice how peer widgets can have different "
$t insert end "font settings, and by default contain all the images "
$t insert end "of the 'parent', but that the embedded windows, "
$t insert end "such as buttons may not appear in the peer.  To ensure "
$t insert end "that embedded windows appear in all peers you can set the "
$t insert end "'-create' option to a script or a string containing %W.  "
$t insert end "(The plot above and the 'Make A Peer' button are "
$t insert end "designed to show up in all peers.)  A good use of "
$t insert end "peers is for "
$t window create end \
  -create {button %W.split -text "Split Windows" -command "textSplitWindow %W" \
	       -cursor top_left_arrow
      blend %W.split} -padx 3
$t insert end " \n\n"

$t insert end "Users of previous versions of Tk will also be interested "
$t insert end "to note that now cursor movement is now by visual line by "
$t insert end "default, and that all scrolling of this widget is by pixel.\n\n"

$t insert end "You may also find it useful to put embedded windows in "
$t insert end "a text without any actual text.  In this case the "
$t insert end "text widget acts like a geometry manager.  For "
$t insert end "example, here is a collection of buttons laid out "
$t insert end "neatly into rows by the text widget.  These buttons "
$t insert end "can be used to change the background color of the "
$t insert end "text widget (\"Default\" restores the color to "
$t insert end "its default).  If you click on the button labeled "
$t insert end "\"Short\", it changes to a longer string so that "
$t insert end "you can see how the text widget automatically "
$t insert end "changes the layout.  Click on the button again "
$t insert end "to restore the short string.\n"

$t insert end "\nNOTE: these buttons will not appear in peers!\n" "peer_warning"
button $t.default -text Default -command "embDefBg $t" \
	-cursor top_left_arrow
$t window create end -window $t.default -padx 3
global embToggle
set embToggle Short
checkbutton $t.toggle -textvariable embToggle -indicatoron 0 \
	-variable embToggle -onvalue "A much longer string" \
	-offvalue "Short" -cursor top_left_arrow -pady 5 -padx 2
$t window create end -window $t.toggle -padx 3 -pady 2
set i 1
foreach color {AntiqueWhite3 Bisque1 Bisque2 Bisque3 Bisque4
	SlateBlue3 RoyalBlue1 SteelBlue2 DeepSkyBlue3 LightBlue1
	DarkSlateGray1 Aquamarine2 DarkSeaGreen2 SeaGreen1
	Yellow1 IndianRed1 IndianRed2 Tan1 Tan4} {
    button $t.color$i -text $color -cursor top_left_arrow -command \
	    "changeBg $t $color"
    $t window create end -window [blend $t.color$i] -padx 3 -pady 2
    incr i
}
$t tag add buttons [blend $t.default] end

button $t.bigB -text "Big borders" -command "textWindBigB $t" \
  -cursor top_left_arrow
button $t.smallB -text "Small borders" -command "textWindSmallB $t" \
  -cursor top_left_arrow
button $t.bigH -text "Big highlight" -command "textWindBigH $t" \
  -cursor top_left_arrow
button $t.smallH -text "Small highlight" -command "textWindSmallH $t" \
  -cursor top_left_arrow
button $t.bigP -text "Big pad" -command "textWindBigP $t" \
  -cursor top_left_arrow
button $t.smallP -text "Small pad" -command "textWindSmallP $t" \
  -cursor top_left_arrow

set text_normal(border) [$t cget -borderwidth]
set text_normal(highlight) [$t cget -highlightthickness]
set text_normal(pad) [$t cget -padx]

$t insert end "\nYou can also change the usual border width and "
$t insert end "highlightthickness and padding.\n"
$t window create end -window [blend $t.bigB]
$t window create end -window [blend $t.smallB]
$t window create end -window [blend $t.bigH]
$t window create end -window [blend $t.smallH]
$t window create end -window [blend $t.bigP]
$t window create end -window [blend $t.smallP]

$t insert end "\n\nFinally, images fit comfortably in text widgets too:"

$t image create end -image \
    [image create photo -file [file join $tk_demoDirectory images ouster.png]]

proc textWindBigB w {
    $w configure -borderwidth 15
}

proc textWindBigH w {
    $w configure -highlightthickness 15
}

proc textWindBigP w {
    $w configure -padx 15 -pady 15
}

proc textWindSmallB w {
    $w configure -borderwidth $::text_normal(border)
}

proc textWindSmallH w {
    $w configure -highlightthickness $::text_normal(highlight)
}

proc textWindSmallP w {
    $w configure -padx $::text_normal(pad) -pady $::text_normal(pad)
}

proc textWindOn w {
    catch {destroy $w.scroll2}
    set t $w.f.text
    ttk::scrollbar $w.scroll2 -orient horizontal -command "$t xview"
    pack $w.scroll2 -after $w.buttons -side bottom -fill x
    $t configure -xscrollcommand "$w.scroll2 set" -wrap none
}

proc textWindOff w {
    catch {destroy $w.scroll2}
    set t $w.f.text
    $t configure -xscrollcommand {} -wrap word
}

proc textWindPlot t {
    set c $t.c
    if {[winfo exists $c]} {
	return
    }

    while {[string first [$t get plot] " \t\n"] >= 0} {
	$t delete plot
    }
    $t insert plot "\n"

    $t window create plot -create {createPlot %W}
    $t tag add center plot
    $t insert plot "\n"
}

proc createPlot {t} {
    set c $t.c

    canvas $c -relief sunken -width 450 -height 300 -cursor top_left_arrow

    set font {Helvetica 18}

    $c create line 100 250 400 250 -width 2
    $c create line 100 250 100 50 -width 2
    $c create text 225 20 -text "A Simple Plot" -font $font -fill brown

    for {set i 0} {$i <= 10} {incr i} {
	set x [expr {100 + ($i*30)}]
	$c create line $x 250 $x 245 -width 2
	$c create text $x 254 -text [expr {10*$i}] -anchor n -font $font
    }
    for {set i 0} {$i <= 5} {incr i} {
	set y [expr {250 - ($i*40)}]
	$c create line 100 $y 105 $y -width 2
	$c create text 96 $y -text [expr {$i*50}].0 -anchor e -font $font
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
    $c bind point <Button-1> "embPlotDown $c %x %y"
    $c bind point <ButtonRelease-1> "$c dtag selected"
    bind $c <B1-Motion> "embPlotMove $c %x %y"
    return $c
}

set embPlot(lastX) 0
set embPlot(lastY) 0

proc embPlotDown {w x y} {
    global embPlot
    $w dtag selected
    $w addtag selected withtag current
    $w raise current
    set embPlot(lastX) $x
    set embPlot(lastY) $y
}

proc embPlotMove {w x y} {
    global embPlot
    $w move selected [expr {$x-$embPlot(lastX)}] [expr {$y-$embPlot(lastY)}]
    set embPlot(lastX) $x
    set embPlot(lastY) $y
}

proc textWindDel t {
    if {[winfo exists $t.c]} {
	$t delete $t.c
	while {[string first [$t get plot] " \t\n"] >= 0} {
	    $t delete plot
	}
	$t insert plot "  "
    }
}

proc changeBg {t c} {
    $t configure -background $c
    if {[tk windowingsystem] eq "aqua"} {
	foreach b [$t window names] {
	    if {[winfo class $b] eq "Button"} {
		$b configure -highlightbackground $c
	    }
	}
    }
}

proc embDefBg t {
    set bg [lindex [$t configure -background] 3]
    changeBg $t $bg
}

proc textMakePeer {parent} {
    set n 1
    while {[winfo exists .peer$n]} { incr n }
    set w [toplevel .peer$n]
    wm title $w "Text Peer #$n"
    frame $w.f -highlightthickness 1 -borderwidth 1 -relief sunken
    set t [$parent peer create $w.f.text -yscrollcommand "$w.scroll set" \
	       -borderwidth 0 -highlightthickness 0]
    $t tag configure peer_warning -font boldFont
    pack $t -expand  yes -fill both
    ttk::scrollbar $w.scroll -command "$t yview"
    pack $w.scroll -side right -fill y
    pack $w.f -expand yes -fill both
}

proc textSplitWindow {textW} {
    if {$textW eq ".twind.f.text"} {
	if {[winfo exists .twind.peer]} {
	    destroy .twind.peer
	} else {
	    set parent [winfo parent $textW]
	    set w [winfo parent $parent]
	    set t [$textW peer create $w.peer \
	      -yscrollcommand "$w.scroll set"]
	    $t tag configure peer_warning -font boldFont
	    $w.pane add $t
	}
    } else {
        return
    }
}
