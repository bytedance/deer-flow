# filebox.tcl --
#
# This demonstration script prompts the user to select a file.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .filebox
catch {destroy $w}
toplevel $w
wm title $w "File Selection Dialogs"
wm iconname $w "filebox"
positionWindow $w

ttk::frame $w._bg
place $w._bg -x 0 -y 0 -relwidth 1 -relheight 1

ttk::label $w.msg -font $font -wraplength 4i -justify left -text "Enter a file name in the entry box or click on the \"Browse\" buttons to select a file name using the file selection dialog."
pack $w.msg -side top

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

foreach i {open save} {
    set f [ttk::frame $w.$i]
    ttk::label $f.lab -text "Select a file to $i: " -anchor e
    ttk::entry $f.ent -width 20
    ttk::button $f.but -text "Browse ..." -command "fileDialog $w $f.ent $i"
    pack $f.lab -side left
    pack $f.ent -side left -expand yes -fill x
    pack $f.but -side left
    pack $f -fill x -padx 1c -pady 3
}

if {[tk windowingsystem] eq "x11"} {
    ttk::checkbutton $w.strict -text "Use Motif Style Dialog" \
	-variable tk_strictMotif -onvalue 1 -offvalue 0
    pack $w.strict -anchor c

    # This binding ensures that we don't run the rest of the demos
    # with motif style interactions
    bind $w.strict <Destroy> {set tk_strictMotif 0}
}

proc fileDialog {w ent operation} {
    #   Type names		Extension(s)	Mac File Type(s)
    #
    #---------------------------------------------------------
    set types {
	{"Text files"		{.txt .doc}	}
	{"Text files"		{}		TEXT}
	{"Tcl Scripts"		{.tcl}		TEXT}
	{"C Source Files"	{.c .h}		}
	{"All Source Files"	{.tcl .c .h}	}
	{"Image Files"		{.gif}		}
	{"Image Files"		{.jpeg .jpg}	}
	{"Image Files"		""		{GIFF JPEG}}
	{"All files"		*}
    }
    if {$operation == "open"} {
	global selected_type
	if {![info exists selected_type]} {
	    set selected_type "Tcl Scripts"
	}
	set file [tk_getOpenFile -filetypes $types -parent $w \
		-typevariable selected_type]
	puts "You selected filetype \"$selected_type\""
    } else {
	set file [tk_getSaveFile -filetypes $types -parent $w \
		-initialfile Untitled -defaultextension .txt]
    }
    if {[string compare $file ""]} {
	$ent delete 0 end
	$ent insert 0 $file
	$ent xview end
    }
}
