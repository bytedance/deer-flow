# items.tcl --
#
# This demonstration script creates a canvas that displays the
# canvas item types.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .items
catch {destroy $w}
toplevel $w
wm title $w "Canvas Item Demonstration"
wm iconname $w "Items"
positionWindow $w
set c $w.frame.c

label $w.msg -font $font -wraplength 5i -justify left -text "This window contains a canvas widget with examples of the various kinds of items supported by canvases.  The following operations are supported:\n  Left-Button drag:\tmoves item under pointer.\n  Middle-Button drag:\trepositions view.\n  Right-Button drag:\tstrokes out area.\n  Ctrl+f:\t\tprints items under area."
pack $w.msg -side top

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

frame $w.frame
pack $w.frame -side top -fill both -expand yes

canvas $c -scrollregion {0c 0c 30c 24c} -width 15c -height 10c \
	-relief sunken -borderwidth 2 \
	-xscrollcommand "$w.frame.hscroll set" \
	-yscrollcommand "$w.frame.vscroll set"
ttk::scrollbar $w.frame.vscroll -command "$c yview"
ttk::scrollbar $w.frame.hscroll -orient horizontal -command "$c xview"

grid $c -in $w.frame \
    -row 0 -column 0 -rowspan 1 -columnspan 1 -sticky news
grid $w.frame.vscroll \
    -row 0 -column 1 -rowspan 1 -columnspan 1 -sticky news
grid $w.frame.hscroll \
    -row 1 -column 0 -rowspan 1 -columnspan 1 -sticky news
grid rowconfig    $w.frame 0 -weight 1 -minsize 0
grid columnconfig $w.frame 0 -weight 1 -minsize 0

# Display a 3x3 rectangular grid.

$c create rect 0c 0c 30c 24c -width 2
$c create line 0c 8c 30c 8c -width 2
$c create line 0c 16c 30c 16c -width 2
$c create line 10c 0c 10c 24c -width 2
$c create line 20c 0c 20c 24c -width 2

set font1 {Helvetica 12}
set font2 {Helvetica 24 bold}
if {[winfo depth $c] > 1} {
    set blue DeepSkyBlue3
    set red red
    set bisque bisque3
    set green SeaGreen3
} else {
    set blue black
    set red black
    set bisque black
    set green black
}

# Set up demos within each of the areas of the grid.

$c create text 5c .2c -text Lines -anchor n
$c create line 1c 1c 3c 1c 1c 4c 3c 4c -width 2m -fill $blue \
	-cap butt -join miter -tags item
$c create line 4.67c 1c 4.67c 4c -arrow last -tags item
$c create line 6.33c 1c 6.33c 4c -arrow both -tags item
$c create line 5c 6c 9c 6c 9c 1c 8c 1c 8c 4.8c 8.8c 4.8c 8.8c 1.2c \
	8.2c 1.2c 8.2c 4.6c 8.6c 4.6c 8.6c 1.4c 8.4c 1.4c 8.4c 4.4c \
	-width 3 -fill $red -tags item
# Main widget program sets variable tk_demoDirectory
$c create line 1c 5c 7c 5c 7c 7c 9c 7c -width .5c \
	-stipple @[file join $tk_demoDirectory images gray25.xbm] \
	-arrow both -arrowshape {15 15 7} -tags item
$c create line 1c 7c 1.75c 5.8c 2.5c 7c 3.25c 5.8c 4c 7c -width .5c \
	-cap round -join round -tags item

$c create text 15c .2c -text "Curves (smoothed lines)" -anchor n
$c create line 11c 4c 11.5c 1c 13.5c 1c 14c 4c -smooth on \
	-fill $blue -tags item
$c create line 15.5c 1c 19.5c 1.5c 15.5c 4.5c 19.5c 4c -smooth on \
	-arrow both -width 3 -tags item
$c create line 12c 6c 13.5c 4.5c 16.5c 7.5c 18c 6c \
	16.5c 4.5c 13.5c 7.5c 12c 6c -smooth on -width 3m -cap round \
	-stipple @[file join $tk_demoDirectory images gray25.xbm] \
	-fill $red -tags item

$c create text 25c .2c -text Polygons -anchor n
$c create polygon 21c 1.0c 22.5c 1.75c 24c 1.0c 23.25c 2.5c \
	24c 4.0c 22.5c 3.25c 21c 4.0c 21.75c 2.5c -fill $green \
	-outline {} -width 4 -tags item
$c create polygon 25c 4c 25c 4c 25c 1c 26c 1c 27c 4c 28c 1c \
	29c 1c 29c 4c 29c 4c -fill $red -outline {} -smooth on -tags item
$c create polygon 22c 4.5c 25c 4.5c 25c 6.75c 28c 6.75c \
	28c 5.25c 24c 5.25c 24c 6.0c 26c 6c 26c 7.5c 22c 7.5c \
	-stipple @[file join $tk_demoDirectory images gray25.xbm] \
	-fill $blue -outline {} -tags item

$c create text 5c 8.2c -text Rectangles -anchor n
$c create rectangle 1c 9.5c 4c 12.5c -outline $red -width 3m -tags item
$c create rectangle 0.5c 13.5c 4.5c 15.5c -fill $green -tags item
$c create rectangle 6c 10c 9c 15c -outline {} \
	-stipple @[file join $tk_demoDirectory images gray25.xbm] \
	-fill $blue -tags item

$c create text 15c 8.2c -text Ovals -anchor n
$c create oval 11c 9.5c 14c 12.5c -outline $red -width 3m -tags item
$c create oval 10.5c 13.5c 14.5c 15.5c -fill $green -tags item
$c create oval 16c 10c 19c 15c -outline {} \
	-stipple @[file join $tk_demoDirectory images gray25.xbm] \
	-fill $blue -tags item

$c create text 25c 8.2c -text Text -anchor n
$c create rectangle 22.4c 8.9c 22.6c 9.1c
$c create text 22.5c 9c -anchor n -font $font1 -width 4c \
	-text "A short string of text, word-wrapped, justified left, and anchored north (at the top).  The rectangles show the anchor points for each piece of text." -tags item
$c create rectangle 25.4c 10.9c 25.6c 11.1c
$c create text 25.5c 11c -anchor w -font $font1 -fill $blue \
	-text "Several lines,\n each centered\nindividually,\nand all anchored\nat the left edge." \
	-justify center -tags item
$c create rectangle 24.9c 13.9c 25.1c 14.1c
catch {
$c create text 25c 14c -font $font2 -anchor c -fill $red -angle 15 \
	-text "Angled characters" -tags item
}

$c create text 5c 16.2c -text Arcs -anchor n
$c create arc 0.5c 17c 7c 20c -fill $green -outline black \
	-start 45 -extent 270 -style pieslice -tags item
$c create arc 6.5c 17c 9.5c 20c -width 4m -style arc \
	-outline $blue -start -135 -extent 270 -tags item \
	-outlinestipple @[file join $tk_demoDirectory images gray25.xbm]
$c create arc 0.5c 20c 9.5c 24c -width 4m -style pieslice \
	-fill {} -outline $red -start 225 -extent -90 -tags item
$c create arc 5.5c 20.5c 9.5c 23.5c -width 4m -style chord \
	-fill $blue -outline {} -start 45 -extent 270  -tags item

$c create text 15c 16.2c -text "Bitmaps and Images" -anchor n
catch {
image create photo items.ousterhout \
    -file [file join $tk_demoDirectory images ouster.png]
image create photo items.ousterhout.active -format "png -alpha 0.5" \
    -file [file join $tk_demoDirectory images ouster.png]
$c create image 13c 20c -tags item -image items.ousterhout \
    -activeimage items.ousterhout.active
}
$c create bitmap 17c 18.5c -tags item \
	-bitmap @[file join $tk_demoDirectory images noletter.xbm]
$c create bitmap 17c 21.5c -tags item \
	-bitmap @[file join $tk_demoDirectory images letters.xbm]

$c create text 25c 16.2c -text Windows -anchor n
button $c.button -text "Press Me" -command "butPress $c $red"
$c create window 21c 18c -window $c.button -anchor nw -tags item
entry $c.entry -width 20 -relief sunken
$c.entry insert end "Edit this text"
$c create window 21c 21c -window $c.entry -anchor nw -tags item
scale $c.scale -from 0 -to 100 -length 6c -sliderlength .4c \
	-width .5c -tickinterval 0
$c create window 28.5c 17.5c -window $c.scale -anchor n -tags item
$c create text 21c 17.9c -text Button: -anchor sw
$c create text 21c 20.9c -text Entry: -anchor sw
$c create text 28.5c 17.4c -text Scale: -anchor s

# Set up event bindings for canvas:

$c bind item <Enter> "itemEnter $c"
$c bind item <Leave> "itemLeave $c"
if {[tk windowingsystem] eq "aqua" && ![package vsatisfies [package provide Tk] 8.7-]} {
    bind $c <Button-2> "itemMark $c %x %y"
    bind $c <B2-Motion> "itemStroke $c %x %y"
    bind $c <Button-3> "$c scan mark %x %y"
    bind $c <B3-Motion> "$c scan dragto %x %y"
} else {
    bind $c <Button-2> "$c scan mark %x %y"
    bind $c <B2-Motion> "$c scan dragto %x %y"
    bind $c <Button-3> "itemMark $c %x %y"
    bind $c <B3-Motion> "itemStroke $c %x %y"
}
bind $c <<NextChar>> "itemsUnderArea $c"
bind $c <Button-1> "itemStartDrag $c %x %y"
bind $c <B1-Motion> "itemDrag $c %x %y"

# Utility procedures for highlighting the item under the pointer:

proc itemEnter {c} {
    global restoreCmd

    if {[winfo depth $c] == 1} {
	set restoreCmd {}
	return
    }
    set type [$c type current]
    if {$type == "window" || $type == "image"} {
	set restoreCmd {}
	return
    } elseif {$type == "bitmap"} {
	set bg [lindex [$c itemconf current -background] 4]
	set restoreCmd [list $c itemconfig current -background $bg]
	$c itemconfig current -background SteelBlue2
	return
    } elseif {$type == "image"} {
	set restoreCmd [list $c itemconfig current -state normal]
	$c itemconfig current -state active
	return
    }
    set fill [lindex [$c itemconfig current -fill] 4]
    if {(($type == "rectangle") || ($type == "oval") || ($type == "arc"))
	    && ($fill == "")} {
	set outline [lindex [$c itemconfig current -outline] 4]
	set restoreCmd "$c itemconfig current -outline $outline"
	$c itemconfig current -outline SteelBlue2
    } else {
	set restoreCmd "$c itemconfig current -fill $fill"
	$c itemconfig current -fill SteelBlue2
    }
}

proc itemLeave {c} {
    global restoreCmd

    eval $restoreCmd
}

# Utility procedures for stroking out a rectangle and printing what's
# underneath the rectangle's area.

proc itemMark {c x y} {
    global areaX1 areaY1
    set areaX1 [$c canvasx $x]
    set areaY1 [$c canvasy $y]
    $c delete area
}

proc itemStroke {c x y} {
    global areaX1 areaY1 areaX2 areaY2
    set x [$c canvasx $x]
    set y [$c canvasy $y]
    if {($areaX1 != $x) && ($areaY1 != $y)} {
	$c delete area
	$c addtag area withtag [$c create rect $areaX1 $areaY1 $x $y \
		-outline black]
	set areaX2 $x
	set areaY2 $y
    }
}

proc itemsUnderArea {c} {
    global areaX1 areaY1 areaX2 areaY2
    set area [$c find withtag area]
    set items ""
    foreach i [$c find enclosed $areaX1 $areaY1 $areaX2 $areaY2] {
	if {[lsearch [$c gettags $i] item] >= 0} {
	    lappend items $i
	}
    }
    puts stdout "Items enclosed by area: $items"
    set items ""
    foreach i [$c find overlapping $areaX1 $areaY1 $areaX2 $areaY2] {
	if {[lsearch [$c gettags $i] item] >= 0} {
	    lappend items $i
	}
    }
    puts stdout "Items overlapping area: $items"
}

set areaX1 0
set areaY1 0
set areaX2 0
set areaY2 0

# Utility procedures to support dragging of items.

proc itemStartDrag {c x y} {
    global lastX lastY
    set lastX [$c canvasx $x]
    set lastY [$c canvasy $y]
}

proc itemDrag {c x y} {
    global lastX lastY
    set x [$c canvasx $x]
    set y [$c canvasy $y]
    $c move current [expr {$x-$lastX}] [expr {$y-$lastY}]
    set lastX $x
    set lastY $y
}

# Procedure that's invoked when the button embedded in the canvas
# is invoked.

proc butPress {w color} {
    set i [$w create text 25c 18.1c -text "Oooohhh!!" -fill $color -anchor n]
    after 500 "$w delete $i"
}
