# textpeer.tcl --
#
# This demonstration script creates a pair of text widgets that can edit a
# single logical buffer. This is particularly useful when editing related text
# in two (or more) parts of the same file.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .textpeer
catch {destroy $w}
toplevel $w
wm title $w "Text Widget Peering Demonstration"
wm iconname $w "textpeer"
positionWindow $w

set count 0

## Define a widget that we peer from; it won't ever actually be shown though
set first [text $w.text[incr count]]
$first insert end "This is a coupled pair of text widgets; they are peers to "
$first insert end "each other. They have the same underlying data model, but "
$first insert end "can show different locations, have different current edit "
$first insert end "locations, and have different selections. You can also "
$first insert end "create additional peers of any of these text widgets using "
$first insert end "the Make Peer button beside the text widget to clone, and "
$first insert end "delete a particular peer widget using the Delete Peer "
$first insert end "button."

## Procedures to make and kill clones; most of this is just so that the demo
## looks nice...
proc makeClone {w parent} {
    global count
    set t [$parent peer create $w.text[incr count] -yscroll "$w.sb$count set"\
		  -height 10 -wrap word]
    set sb [ttk::scrollbar $w.sb$count -command "$t yview" -orient vertical]
    set b1 [button $w.clone$count -command "makeClone $w $t" \
		    -text "Make Peer"]
    set b2 [button $w.kill$count -command "killClone $w $count" \
		    -text "Delete Peer"]
    set row [expr {$count * 2}]
    grid $t $sb $b1 -sticky nsew -row $row
    grid ^  ^   $b2 -row [incr row]
    grid configure $b1 $b2 -sticky new
    grid rowconfigure $w $b2 -weight 1
}
proc killClone {w count} {
    destroy $w.text$count $w.sb$count
    destroy $w.clone$count $w.kill$count
}

## Now set up the GUI
makeClone $w $first
makeClone $w $first
destroy $first

## See Code / Dismiss buttons
grid [addSeeDismiss $w.buttons $w] - - -sticky ew -row 5000
grid columnconfigure $w 0 -weight 1
