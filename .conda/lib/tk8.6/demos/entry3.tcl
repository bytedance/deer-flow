# entry3.tcl --
#
# This demonstration script creates several entry widgets whose
# permitted input is constrained in some way.  It also shows off a
# password entry.

if {![info exists widgetDemo]} {
    error "This script should be run from the \"widget\" demo."
}

package require Tk

set w .entry3
catch {destroy $w}
toplevel $w
wm title $w "Constrained Entry Demonstration"
wm iconname $w "entry3"
positionWindow $w

label $w.msg -font $font -wraplength 5i -justify left -text "Four different\
	entries are displayed below.  You can add characters by pointing,\
	clicking and typing, though each is constrained in what it will\
	accept.  The first only accepts 32-bit integers or the empty string\
	(checking when focus leaves it) and will flash to indicate any\
	problem.  The second only accepts strings with fewer than ten\
	characters and sounds the bell when an attempt to go over the limit\
	is made.  The third accepts US phone numbers, mapping letters to\
	their digit equivalent and sounding the bell on encountering an\
	illegal character or if trying to type over a character that is not\
	a digit.  The fourth is a password field that accepts up to eight\
	characters (silently ignoring further ones), and displaying them as\
	asterisk characters."

## See Code / Dismiss buttons
set btns [addSeeDismiss $w.buttons $w]
pack $btns -side bottom -fill x

# focusAndFlash --
# Error handler for entry widgets that forces the focus onto the
# widget and makes the widget flash by exchanging the foreground and
# background colours at intervals of 200ms (i.e. at approximately
# 2.5Hz).
#
# Arguments:
# W -		Name of entry widget to flash
# fg -		Initial foreground colour
# bg -		Initial background colour
# count -	Counter to control the number of times flashed

proc focusAndFlash {W fg bg {count 9}} {
    focus -force $W
    if {$count<1} {
	$W configure -foreground $fg -background $bg
    } else {
	if {$count%2} {
	    $W configure -foreground $bg -background $fg
	} else {
	    $W configure -foreground $fg -background $bg
	}
	after 200 [list focusAndFlash $W $fg $bg [expr {$count-1}]]
    }
}

labelframe $w.l1 -text "Integer Entry"
# Alternatively try using {string is digit} for arbitrary length numbers,
# and not just 32-bit ones.
entry $w.l1.e -validate focus -vcmd {string is integer %P}
$w.l1.e configure -invalidcommand \
	"focusAndFlash %W [$w.l1.e cget -fg] [$w.l1.e cget -bg]"
pack $w.l1.e -fill x -expand 1 -padx 1m -pady 1m

labelframe $w.l2 -text "Length-Constrained Entry"
entry $w.l2.e -validate key -invcmd bell -vcmd {expr {[string length %P]<10}}
pack $w.l2.e -fill x -expand 1 -padx 1m -pady 1m

### PHONE NUMBER ENTRY ###
# Note that the source to this is quite a bit longer as the behaviour
# demonstrated is a lot more ambitious than with the others.

# Initial content for the third entry widget
set entry3content "1-(000)-000-0000"
# Mapping from alphabetic characters to numbers.  This is probably
# wrong, but it is the only mapping I have; the UK doesn't really go
# for associating letters with digits for some reason.
set phoneNumberMap {}
foreach {chars digit} {abc 2 def 3 ghi 4 jkl 5 mno 6 pqrs 7 tuv 8 wxyz 9} {
    foreach char [split $chars ""] {
	lappend phoneNumberMap $char $digit [string toupper $char] $digit
    }
}

# validatePhoneChange --
# Checks that the replacement (mapped to a digit) of the given
# character in an entry widget at the given position will leave a
# valid phone number in the widget.
#
# W -	  The entry widget to validate
# vmode - The widget's validation mode
# idx -	  The index where replacement is to occur
# char -  The character (or string, though that will always be
#	  refused) to be overwritten at that point.

proc validatePhoneChange {W vmode idx char} {
    global phoneNumberMap entry3content
    if {$idx < 0} {return 1}
    after idle [list $W configure -validate $vmode -invcmd bell]
    if {
	!($idx<3 || $idx==6 || $idx==7 || $idx==11 || $idx>15) &&
	[string match {[0-9A-Za-z]} $char]
    } then {
	$W delete $idx
	$W insert $idx [string map $phoneNumberMap $char]
	after idle [list phoneSkipRight $W -1]
	return 1
    }
    return 0
}

# phoneSkipLeft --
# Skip over fixed characters in a phone-number string when moving left.
#
# Arguments:
# W -	The entry widget containing the phone-number.

proc phoneSkipLeft {W} {
    set idx [$W index insert]
    if {$idx == 8} {
	# Skip back two extra characters
	$W icursor [incr idx -2]
    } elseif {$idx == 7 || $idx == 12} {
	# Skip back one extra character
	$W icursor [incr idx -1]
    } elseif {$idx <= 3} {
	# Can't move any further
	bell
	return -code break
    }
}

# phoneSkipRight --
# Skip over fixed characters in a phone-number string when moving right.
#
# Arguments:
# W -	The entry widget containing the phone-number.
# add - Offset to add to index before calculation (used by validation.)

proc phoneSkipRight {W {add 0}} {
    set idx [$W index insert]
    if {$idx+$add == 5} {
	# Skip forward two extra characters
	$W icursor [incr idx 2]
    } elseif {$idx+$add == 6 || $idx+$add == 10} {
	# Skip forward one extra character
	$W icursor [incr idx]
    } elseif {$idx+$add == 15 && !$add} {
	# Can't move any further
	bell
	return -code break
    }
}

labelframe $w.l3 -text "US Phone-Number Entry"
entry $w.l3.e -validate key  -invcmd bell  -textvariable entry3content \
	-vcmd {validatePhoneChange %W %v %i %S}
# Click to focus goes to the first editable character...
bind $w.l3.e <FocusIn> {
    if {"%d" ne "NotifyAncestor"} {
	%W icursor 3
	after idle {%W selection clear}
    }
}
bind $w.l3.e <<PrevChar>> {phoneSkipLeft  %W}
bind $w.l3.e <<NextChar>> {phoneSkipRight %W}
pack $w.l3.e -fill x -expand 1 -padx 1m -pady 1m

labelframe $w.l4 -text "Password Entry"
entry $w.l4.e -validate key -show "*" -vcmd {expr {[string length %P]<=8}}
pack $w.l4.e -fill x -expand 1 -padx 1m -pady 1m

lower [frame $w.mid]
grid $w.l1 $w.l2 -in $w.mid -padx 3m -pady 1m -sticky ew
grid $w.l3 $w.l4 -in $w.mid -padx 3m -pady 1m -sticky ew
grid columnconfigure $w.mid {0 1} -uniform 1
pack $w.msg -side top
pack $w.mid -fill both -expand 1
