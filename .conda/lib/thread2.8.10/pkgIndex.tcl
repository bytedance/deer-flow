# -*- tcl -*-
# Tcl package index file, version 1.1
#

if {![package vsatisfies [package provide Tcl] 8.4]} {
    # Pre-8.4 Tcl interps we dont support at all.  Bye!
    # 9.0+ Tcl interps are only supported on 32-bit platforms.
    if {![package vsatisfies [package provide Tcl] 9.0]
	    || ($::tcl_platform(pointerSize) != 4)} {
	return
    }
}

# All Tcl 8.4+ interps can [load] Thread 2.8.10
#
# For interps that are not thread-enabled, we still call [package ifneeded].
# This is contrary to the usual convention, but is a good idea because we
# cannot imagine any other version of Thread that might succeed in a
# thread-disabled interp.  There's nothing to gain by yielding to other
# competing callers of [package ifneeded Thread].  On the other hand,
# deferring the error has the advantage that a script calling
# [package require Thread] in a thread-disabled interp gets an error message
# about a thread-disabled interp, instead of the message
# "can't find package Thread".

package ifneeded Thread 2.8.10 [list load [file join $dir libthread2.8.10.so] [string totitle thread]]

# package Ttrace uses some support machinery.

# In Tcl 8.4 interps we use some older interfaces
if {![package vsatisfies [package provide Tcl] 8.5]} {
    package ifneeded Ttrace 2.8.10 "
    [list proc thread_source {dir} {
	if {[info exists ::env(TCL_THREAD_LIBRARY)] &&
		[file readable $::env(TCL_THREAD_LIBRARY)/ttrace.tcl]} {
	    source -encoding utf-8 $::env(TCL_THREAD_LIBRARY)/ttrace.tcl
	} elseif {[file readable [file join $dir .. lib ttrace.tcl]]} {
	    source -encoding utf-8 [file join $dir .. lib ttrace.tcl]
	} elseif {[file readable [file join $dir ttrace.tcl]]} {
	    source -encoding utf-8 [file join $dir ttrace.tcl]
	}
	if {[namespace which ::ttrace::update] ne ""} {
	    ::ttrace::update
	}
    }]
    [list thread_source $dir]
    [list rename thread_source {}]"
    return
}

# In Tcl 8.5+ interps; use [::apply]

package ifneeded Ttrace 2.8.10 [list ::apply {{dir} {
    if {[info exists ::env(TCL_THREAD_LIBRARY)] &&
	[file readable $::env(TCL_THREAD_LIBRARY)/ttrace.tcl]} {
	source -encoding utf-8 $::env(TCL_THREAD_LIBRARY)/ttrace.tcl
    } elseif {[file readable [file join $dir .. lib ttrace.tcl]]} {
	source -encoding utf-8 [file join $dir .. lib ttrace.tcl]
    } elseif {[file readable [file join $dir ttrace.tcl]]} {
	source -encoding utf-8 [file join $dir ttrace.tcl]
    }
    if {[namespace which ::ttrace::update] ne ""} {
	::ttrace::update
    }
}} $dir]



