# tree.tcl --
#
# This demonstration script creates a toplevel window containing a Ttk
# tree widget.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .tree
catch {destroy $w}
toplevel $w
wm title $w "Directory Browser"
wm iconname $w "tree"
positionWindow $w

## Explanatory text
ttk::label $w.msg -font $font -wraplength 4i -justify left -anchor n -padding {10 2 10 6} -text "Ttk is the new Tk themed widget set. One of the widgets it includes is a tree widget, which allows the user to browse a hierarchical data-set such as a filesystem. The tree widget not only allows for the tree part itself, but it also supports an arbitrary number of additional columns which can show additional data (in this case, the size of the files found in your filesystem). You can also change the width of the columns by dragging the boundary between them."
pack $w.msg -fill x

## See Code / Dismiss
pack [addSeeDismiss $w.seeDismiss $w] -side bottom -fill x

## Code to populate the roots of the tree (can be more than one on Windows)
proc populateRoots {tree} {
    foreach dir [lsort -dictionary [file volumes]] {
	populateTree $tree [$tree insert {} end -text $dir \
		-values [list $dir directory]]
    }
}

## Code to populate a node of the tree
proc populateTree {tree node} {
    if {[$tree set $node type] ne "directory"} {
	return
    }
    set path [$tree set $node fullpath]
    $tree delete [$tree children $node]
    foreach f [lsort -dictionary [glob -nocomplain -dir $path *]] {
	set f [file normalize $f]
	set type [file type $f]
	set id [$tree insert $node end -text [file tail $f] \
		-values [list $f $type]]

	if {$type eq "directory"} {
	    ## Make it so that this node is openable
	    $tree insert $id 0 -text dummy ;# a dummy
	    $tree item $id -text [file tail $f]/

	} elseif {$type eq "file"} {
	    set size [file size $f]
	    ## Format the file size nicely
	    if {$size >= 1024*1024*1024} {
		set size [format %.1f\ GB [expr {$size/1024/1024/1024.}]]
	    } elseif {$size >= 1024*1024} {
		set size [format %.1f\ MB [expr {$size/1024/1024.}]]
	    } elseif {$size >= 1024} {
		set size [format %.1f\ kB [expr {$size/1024.}]]
	    } else {
		append size " bytes"
	    }
	    $tree set $id size $size
	}
    }

    # Stop this code from rerunning on the current node
    $tree set $node type processedDirectory
}

## Create the tree and set it up
ttk::treeview $w.tree -columns {fullpath type size} -displaycolumns {size} \
	-yscroll "$w.vsb set" -xscroll "$w.hsb set"
ttk::scrollbar $w.vsb -orient vertical -command "$w.tree yview"
ttk::scrollbar $w.hsb -orient horizontal -command "$w.tree xview"
$w.tree heading \#0 -text "Directory Structure"
$w.tree heading size -text "File Size"
$w.tree column size -width 70
populateRoots $w.tree
bind $w.tree <<TreeviewOpen>> {populateTree %W [%W focus]}

## Arrange the tree and its scrollbars in the toplevel
lower [ttk::frame $w.dummy]
pack $w.dummy -fill both -expand 1
grid $w.tree $w.vsb -sticky nsew -in $w.dummy
grid $w.hsb -sticky nsew -in $w.dummy
grid columnconfigure $w.dummy 0 -weight 1
grid rowconfigure $w.dummy 0 -weight 1
