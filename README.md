# init project

virtualenv pecan_env
cd pecan_env
source bin/activate
pip install pecan

pecan create web_server_pecan
alias tree="find web_server_pecan/ -print | sed -e 's;[^/]*/;|____;g;s;____|;|;g'"        

tree web_server_pecan         
|____       
||____config.py         
||____MANIFEST.in       
||____public        
|||____css          
||||____style.css         
|||____images       
||||____logo.png        
||____setup.cfg       
||____setup.py        
||____web_server_pecan        
|||______init__.py        
|||______init__.pyc       
|||____app.py       
|||____controllers        
||||______init__.py       
||||______init__.pyc        
||||____root.py       
||||____root.pyc        
|||____model        
||||______init__.py        
||||______init__.pyc                
|||____templates        
||||____error.html        
||||____index.html        
||||____layout.html       
|||____tests        
||||______init__.py       
||||____config.py       
||||____test_functional.py        
||||____test_units.py       
||||____test_units.pyc        

# tips

## WSME
web service Made Easy

