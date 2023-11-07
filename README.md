# vyper halmos pipeline

a (work in progress) pipeline for generating formal verification tests from vyper contracts

## tl dr

the pipeline takes in vyper contracts and compiles three versions: 0.3.9, 0.3.10 (unoptimized), and 0.3.10 (optimized).

it then uses [halmos](https://github.com/a16z/halmos) to pass arbitrary calldata to these contracts, ensuring that all view functions return the same values after the call.

## how to use

1) create and activate a virtual environment with vyper 0.3.10 installed
2) run `python pipeline.py` to generate files with 0.3.10 (optimized and unoptimized) bytecode included
3) create and activate a virtual environment with vyper 0.3.9 installed
4) run `python replace_old.py` to add the 0.3.9 bytecode to the files generated in step 2

## to do

1) the tests generated in halmos are currently having problems. they are creating many invalid counterexamples, which i haven't had time to debug. solving this likely involves making some fixes to halmos itself, which is a worthwhile project. [join their telegram](https://t.me/+4UhzHduai3MzZmUx) if you're interested in taking this one.
2) the pipeline is pretty hacky. it was not meant as a production tool but an internal idea i tried to use for the [codehawks](https://www.codehawks.com/) audit. there is lots of cleanup that could be done, including compiling both versions bytecode from one command.
3) argument encoding for more obscure types (like structs or long arrays) are simply skipped, and could be reasonable included with some extra engineering.
4) in a production ready end state, this could be deployed as a CI tool, where contracts upgrading to new vyper versions are verified for correctness against the previous versions. tbd.
