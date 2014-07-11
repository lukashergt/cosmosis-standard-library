from cosmosis import option_section

def setup(options):
	source = str(options[option_section, "source"])
	dest = str(options[option_section, "dest"])
	return (source, dest)

def execute(block, config):
	source, dest = config
	block._copy_section(source, dest)
	block._delete_section(source)
	return 0

def cleanup(config):
	pass