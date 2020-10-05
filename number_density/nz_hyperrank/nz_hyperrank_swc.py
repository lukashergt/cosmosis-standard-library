"""
The Hyperrank module replaces 'load_nz_fits' and 'photoz_bias' to allow
marginalization of redshift systematics using a pool of distributions rather
than nuisance parameters.

On setup, realisations are read from an input file, ranked based on a
chatacteristic value of the whole distribution or their individual tomographic
bins and returned as an array.

Modes are:
'no-rank':
    No ranking. NZ array is filled on the same order the realisations are
    provided in the input fits file

'unified':
    Realisations are ranked according to the combined mean redshift across
    all tomographic bins and stored in the NZ array

'separate':
    Individual tomographic bins are ranked according to their mean
    redshift and stored on the NZ.

'external':
    Realisations are ranked according to the values on an external file.
    Values on the external file can be either the desired rank, or any
    other characteristic value describing the realisations.

'random':
    A random sequence of numbers is used to rank the distributions.
    This sequence then must remain constant during the pipeline.
    How do we keep the same ordering for all spawned processes?
    For now, just use the same random seed for all.

'inv-chi-unified':
    Similar to unified, but this time realisations are ranked according
    to the combined mean inverse comoving distance across all tomographic
    bins.

'inv-chi-separate':
    Similar to separete, but this time individual tomographic bins are
    ranked according to their mean inverse comoving distance.

On execute, the sampled n(z) is chosen based on the value of rank_hyperparm_i
defined by the sampler, which in turn is mapped to the rankings defined in
setup.
"""

try:
    from cosmosis.datablock import names, option_section
    #from cosmosis.datablock import option_section
except:
    option_section = "options"
import numpy as np
from nz_gz import nz_to_gchi

try:
    import astropy.io.fits as pyfits
except ImportError:
    try:
        import pyfits
    except ImportError:
        raise RuntimeError("You need astropy installed to use the module \
        nz-hyperrank; try running: pip install astropy.")

modes = ['unified',
         'separate',
         'inv-chi-unified',
         'inv-chi-separate',
         'random',
         'external',
         'no-rank']

def load_histogram_form(ext, bin, upsampling):
    # Load the various z columns.
    # The cosmosis code is expecting something it can spline
    # so  we need to give it more points than this - we will
    # give it the intermediate z values (which just look like a step
    # function)
    zlow = ext.data['Z_LOW']
    zhigh = ext.data['Z_HIGH']

    if upsampling == 1:
        z = ext.data['Z_MID']
        nz = ext.data['BIN{0}'.format(bin)]

    else:
        z = np.linspace(0.0, zhigh[-1], len(zlow) * upsampling)
        sample_bin = np.digitize(z, zlow) - 1
        nz = ext.data['BIN{0}'.format(bin)][sample_bin]



#    norm = np.trapz(nz, z)
    norm = np.sum(nz)
# Capture the normalization as m-priors
    mbias = norm-1.
    nz /= norm


    return z, nz, mbias

def ensure_starts_at_zero(z, nz):
    nbin = nz.shape[0]
    if z[0] > 0.00000001:
        z_new = np.zeros(len(z) + 1)
        z_new[1:] = z
        nz_new = np.zeros((nbin, len(z) + 1))
        nz_new[:, 1:] = nz
        nz_new[nz_new < 0] = 0
    else:
        z_new = z
        nz_new = nz
        nz_new[nz_new < 0] = 0
    return z_new, nz_new


def setup(options):
    # Returns a dictionary with an array of the realisations ranked according
    # the ranking mode.
    # The dictionary also includes additional information of the array and
    # selected modes.

    mode = options[option_section, 'mode']

    if mode not in modes:
        raise RuntimeError('Invalid mode set in config file. Please set one of\
        (inv-chi-)unified, (inv-chi-)separate, random or external')

    # Read configuration from inifile
    nz_filename = options[option_section, 'nz_file']
    data_set = options.get_string(option_section, "data_set")
    upsampling = options.get_int(option_section, 'upsampling', 1)
    verbose = options.get_bool(option_section, 'verbose', False)
    rank_output = options.get_string(option_section, 'rank_output', 'ranks_{0}.txt'.format(mode))
    weighting = options.get_bool(option_section, 'weight', False)

    nz_file = pyfits.open(nz_filename)

    n_realisations = 0
    n_bins = 0
    for iext in np.arange(1, len(nz_file)):
        if nz_file[iext].header['EXTNAME'].startswith('nz_{0}_realisation'.format(data_set)):
            n_realisations += 1
        if nz_file[iext].header['EXTNAME'].startswith('nz_{0}_realisation_0'.format(data_set)):
            n_hist = len(nz_file[iext].data['Z_MID'])
            for col in nz_file[iext].data.columns:
                if col.name.startswith('BIN'):
                    n_bins += 1

    print('Hyperrank detected {0} realisations, {1} tomographic bins, {2} histogram bins. Ranking them using {3} mode.'.format(n_realisations, n_bins, n_hist, mode.upper()))

    # Initialize arrays for characteristic values from realisations
    nz = np.zeros([n_realisations, n_bins, n_hist*upsampling])
    multiplicative_bias = np.zeros([n_realisations, n_bins])
    gchi = np.zeros([n_realisations, n_bins, n_hist*upsampling])
    chi = np.zeros([n_realisations, n_bins, n_hist*upsampling])
    nz_mean = np.zeros([n_realisations, n_bins])
    inv_chi_mean = np.zeros([n_realisations, n_bins])
    weights = np.ones(n_realisations)

    # Read all extensions from the input nz file and obtain their mean redshifts
    # and mean inverse comoving distances for all tomographic bins.

    for iext in np.arange(n_realisations):

        extname = 'nz_'+data_set+'_realisation_{0}'.format(iext)
        ext = nz_file[extname]

        if weighting:
            try:
                weights[iext] = ext.header['weight']
            except KeyError:
                weights[iext] = 0
        for ibin in np.arange(1, n_bins+1):
            zmid, nz[iext, ibin-1], multiplicative_bias[iext,ibin-1]   = load_histogram_form(ext, ibin, upsampling)
            nz_mean[iext, ibin-1] = np.trapz(nz[iext, ibin-1]*zmid, zmid)
            if mode.startswith('inv-chi'):
                chi, gchi[iext, ibin-1] = nz_to_gchi(zmid, nz[iext, ibin-1])
                inv_chi_mean[iext, ibin-1] = np.trapz(nz[iext, ibin-1]/chi, chi)

    ### Find mean and std of multiplicative bias:
    for i in range(1,n_bins+1):
        mean=np.mean(multiplicative_bias[:,i-1])
	std =np.std(multiplicative_bias[:,i-1])
	print 'mean,std of m in bin', i,' is ', mean,std
    # Check that at least one weight is larger than zero. Issue warning if at least one is zero
    if np.array_equal(np.array([0]) , np.unique(weights)):
        raise RuntimeError("All realisations have zero weight. Set weight = False in the hyperrank configuration or check the weight key in the header of the input datafile")
    elif 0 in weights:
        print("Hyperrank warning: one or more realisations have zero weight")

    # For comparison with fiducial realisation
    fiducial = True
    try:
        nz_file.index_of('nz_{0}'.format(data_set))
    except KeyError:
        fiducial = False

    if mode in ['unified', 'inv-chi-unified'] and fiducial:

        nz_mean_fid = np.zeros(n_bins)
        gchi_mean_fid = np.zeros(n_bins)

        for ibin in np.arange(1, n_bins+1):

            zmid_fid = nz_file['nz_{0}'.format(data_set)].data['Z_MID']
            nz_fid = nz_file['nz_{0}'.format(data_set)].data['BIN{0}'.format(ibin)]
            nz_mean_fid[ibin-1] = np.trapz(zmid_fid*nz_fid, zmid_fid)

            if mode.startswith('inv-chi'):
                chi_fid, gchi_fid = nz_to_gchi(zmid_fid, nz_fid)
                inv_chi_mean_fid[ibin-1] = np.trapz(nz_fid/chi_fid, chi_fid)

        nz_mean_fid = np.mean(nz_mean_fid)
        gchi_mean_fid = np.mean(gchi_mean_fid)

    # Depending on the mode selected, ranking begins here based on the nz_mean
    # or inv_chi_mean arrays.
    if mode == 'no-rank':

        order = np.arange(n_realisations)
        rank = np.argsort(order)

        ranked_nz = nz
        ranked_nz_mean = nz_mean


    if mode == 'unified':
        nz_mean = nz_mean.mean(axis=1)

        order = np.argsort(nz_mean)
        rank = np.argsort(order)

        ranked_nz = nz[order]
	ranked_cal = multiplicative_bias[order]
	
        ranked_nz_mean = nz_mean[order]

        if verbose and fiducial:
            fid_rank = np.searchsorted(ranked_nz_mean, nz_mean_fid)
            print('Fiducial {0} realisation would have been ranked in {1} position with an approximate value for rank_hyperparm_1 = {2}'.format(data_set, fid_rank, float(fid_rank)/float(n_realisations)))


    if mode == 'separate':
        ranked_nz = np.empty([n_realisations, n_bins, n_hist*upsampling])
        rank = np.empty([n_realisations, n_bins])
        order = np.zeros([n_realisations, n_bins], dtype=int)
        for ibin in np.arange(1, n_bins+1):

            nz_mean_bin = nz_mean[:, ibin-1]

            order[:, ibin-1] = np.argsort(nz_mean_bin)
            rank[:, ibin-1] = np.argsort(order[:, ibin-1])

            ranked_nz[:, ibin-1] = nz[order[:, ibin-1], ibin-1]
            ranked_nz_mean = nz_mean[order[:, ibin-1], ibin-1]


    if mode == 'external':
        external_filename = options[option_section, 'external_ranking_filename']
        if external_filename == "":
            raise RuntimeError('Set external mode but no input file defined. Aborting')

        external = np.genfromtxt(external_filename)
        order = np.argsort(external)
        rank = np.argsort(order)

        ranked_nz = nz[order]


    if mode == 'random':
        np.random.seed(n_realisations)

        order = np.arange(n_realisations)
        np.random.shuffle(order)
        rank = np.argsort(order)
        ranked_nz = nz[order]


    if mode == 'inv-chi-unified':
        inv_chi_mean = inv_chi_mean.mean(axis=1)

        order = np.argsort(inv_chi_mean)
        rank = np.argsort(order)

        ranked_nz = nz[order]
        ranked_nz_inv_chi_mean = inv_chi_mean[order]

        if verbose and fiducial:
            fid_rank = np.searchsorted(ranked_nz_inv_chi_mean, gchi_mean_fid)
            print('Fiducial {0} realisation would have been ranked in {1} position with an approximate value for rank_hyperparm_1 = {2}'.format(data_set, fid_rank, fid_rank/n_realisations))


    if mode == 'inv-chi-separate':
        ranked_nz = np.empty([n_realisations, n_bins, n_hist*upsampling])
        rank = np.empty([n_realisations, n_bins])
        order = np.empty([n_realisations, n_bins], dtype=int)
        for ibin in np.arange(1, n_bins+1):

            inv_chi_mean_bin = inv_chi_mean[:, ibin-1]

            order[:, ibin-1] = np.argsort(inv_chi_mean_bin)
            rank[:, ibin-1] = np.argsort(order[:, ibin-1])

            ranked_nz[:, ibin-1] = nz[order[:, ibin-1], ibin-1]
            ranked_nz_inv_chi_mean = inv_chi_mean[order[:, ibin-1], ibin-1]

    cal_section = options.get_string(
        option_section, "cal_section", default=names.shear_calibration_parameters)

    # create config dictionary with ranked rel and return it
    config = {}
    config['sample'] = data_set.upper()
    config['ranked_nz'] = ranked_nz
    config['mode'] = mode
    config['n_realisations'] = n_realisations
    config['zmid'] = zmid
    config['n_bins'] = n_bins
    config['n_hist'] = n_hist*upsampling
    config['ranked_cal'] = ranked_cal
    config['cal_section'] = cal_section

    weight_sum = np.sum(weights)
    weights = weights[order]
    weight_cumsum = np.cumsum(weights, axis=0) / weight_sum
    config['weights'] = weight_cumsum

    if verbose:
        np.savetxt(rank_output, rank, fmt='%d')

    return config


def execute(block, config):
    # Stores the sampled redshift distribution in the datablock by reading the
    # sampled rank_hyperparm_i values and mapping the ranked distributions to the
    # range of values rank_hyperparm_i can take, [0, 1)
    # There are two families of rank modes: Unified modes and separate modes.


    ranked_nz = config['ranked_nz']
    mode = config['mode']
    pz = 'NZ_' + config['sample']
    cal_section = config['cal_section']
    n_realisations = config['n_realisations']
    nbin = config['n_bins']
    nhist = config['n_hist']
    weights = config['weights']
    ranked_cal = config['ranked_cal']

    block[pz, 'nbin'] = config['n_bins']

    if mode in ['no-rank', 'unified', 'random', 'external', 'inv-chi-unified']:
        # A single rank_hyperparm_1 values is required, since all realisations
        # are considered a fixed collection of tomographic bins.
        rank = block['ranks', 'rank_hyperparm_1']
        sample = np.searchsorted(weights, rank)

	mbias = ranked_cal[sample]
        for ibin in range(nbin):
	    block[cal_section, "m{}".format(ibin + 1)] = mbias[ibin]
	    #print 'shear calibration in bin ', ibin, '= ', mbias[ibin]

        z, nz_sampled = ensure_starts_at_zero(config['zmid'], ranked_nz[sample])
        block[pz, 'z'] = z
        block[pz, 'nz'] = len(z)

        # write the nz to the data block. pz is the name of the data_set
        for ibin in np.arange(1, nbin+1):
            block[pz, 'bin_{0}'.format(ibin)] = nz_sampled[ibin-1]

    if mode in ['separate', 'inv-chi-separate']:
        # A rank_hyperparm_i values for each tomographic bin is required
        # Realisations are not considered fixed groups of tomographic bins.
        # i.e., tomographic bin mixing is allowed.
        nz_sampled = np.empty([nbin, nhist])
        for ibin in np.arange(1, nbin+1):
            rank = block['ranks', 'rank_hyperparm_{0}'.format(ibin)]
            sample = np.searchsorted(weights[:,ibin-1], rank)
            nz_sampled[ibin-1] = ranked_nz[sample, ibin-1]

        z, nz_sampled = ensure_starts_at_zero(config['zmid'], nz_sampled)
        block[pz, 'z'] = z
        block[pz, 'nz'] = len(z)

# Add in the impact of uncertainty from image simulations.
# This will both change the n(z) and then save the normalization as 
# a multiplicative bias (since the n's will get re-normalized later on).        
# write the nz to the data block. pz is the name of the data_set
        for ibin in np.arange(1, nbin+1):
            block[pz, 'bin_{0}'.format(ibin)] = nz_sampled[ibin-1]

    return 0


def cleanup(config):

    return 0
