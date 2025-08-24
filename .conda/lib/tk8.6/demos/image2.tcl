# image2.tcl --
#
# This demonstration script creates a simple collection of widgets
# that allow you to select and view images in a Tk label.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

# loadDir --
# This procedure reloads the directory listbox from the directory
# named in the demo's entry.
#
# Arguments:
# w -			Name of the toplevel window of the demo.

proc loadDir w {
    global dirName

    $w.f.list delete 0 end
    foreach i [lsort [glob -type f -directory $dirName *]] {
	$w.f.list insert end [file tail $i]
    }
}

# selectAndLoadDir --
# This procedure pops up a dialog to ask for a directory to load into
# the listobx and (if the user presses OK) reloads the directory
# listbox from the directory named in the demo's entry.
#
# Arguments:
# w -			Name of the toplevel window of the demo.

proc selectAndLoadDir w {
    global dirName
    set dir [tk_chooseDirectory -initialdir $dirName -parent $w -mustexist 1]
    if {$dir ne ""} {
	set dirName $dir
	loadDir $w
    }
}

# loadImage --
# Given the name of the toplevel window of the demo and the mouse
# position, extracts the directory entry under the mouse and loads
# that file into a photo image for display.
#
# Arguments:
# w -			Name of the toplevel window of the demo.
# x, y-			Mouse position within the listbox.

proc loadImage {w x y} {
    global dirName

    set file [file join $dirName [$w.f.list get @$x,$y]]
    if {[catch {
	image2a configure -file $file
    }]} then {
	# Mark the file as not loadable
	$w.f.list itemconfigure @$x,$y -bg \#c00000 -selectbackground \#ff0000
    }
}

set w .image2
catch {destroy $w}
toplevel $w
wm title $w "Image Demonstration #2"
wm iconname $w "Image2"
positionWindow $w

label $w.msg -font $font -wraplength 4i -justify left -text "This demonstration allows you to view images using a Tk \"photo\" image.  First type a directory name in the listbox, then type Return to load the directory into the listbox.  Then double-click on a file name in the listbox to see that image."
pack $w.msg -side top

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

frame $w.mid
pack $w.mid -fill both -expand 1

labelframe $w.dir -text "Directory:"
# Main widget program sets variable tk_demoDirectory
set dirName [file join $tk_demoDirectory images]
entry $w.dir.e -width 30 -textvariable dirName
button $w.dir.b -pady 0 -padx 2m -text "Select Dir." \
	-command "selectAndLoadDir $w"
bind $w.dir.e <Return> "loadDir $w"
pack $w.dir.e -side left -fill both -padx 2m     -pady 2m -expand true
pack $w.dir.b -side left -fill y    -padx {0 2m} -pady 2m
labelframe $w.f -text "File:" -padx 2m -pady 2m

listbox $w.f.list -width 20 -height 10 -yscrollcommand "$w.f.scroll set"
ttk::scrollbar $w.f.scroll -command "$w.f.list yview"
pack $w.f.list $w.f.scroll -side left -fill y -expand 1
$w.f.list insert 0 earth.gif earthris.gif teapot.ppm
bind $w.f.list <Double-Button-1> "loadImage $w %x %y"

catch {image delete image2a}
image create photo image2a
labelframe $w.image -text "Image:"
label $w.image.image -image image2a
pack $w.image.image -padx 2m -pady 2m

grid $w.dir -        -sticky ew -padx 1m -pady 1m -in $w.mid
grid $w.f   $w.image -sticky nw -padx 1m -pady 1m -in $w.mid
grid columnconfigure $w.mid 1 -weight 1
