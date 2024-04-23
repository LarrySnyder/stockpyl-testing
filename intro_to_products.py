from stockpyl.supply_chain_node import SupplyChainNode
from stockpyl.supply_chain_product import SupplyChainProduct
from stockpyl.supply_chain_network import serial_system
from stockpyl.policy import Policy
from stockpyl.sim import simulation
from stockpyl.sim_io import write_results


"""Nodes function basically like they did before, except that now nodes can "handle" products.
Every node handles at least one product; if a product hasn't been explicitly specified
by the user, the simulation creates a dummy product.

For now, the network-building functions don't handle products, so you have to add the
products to the nodes after you create the network.

Most SupplyChainNode attributes (local_holding_cost, shipment_lead_time, demand_source, etc.) are
also attributes of SupplyChainProducts. This allows you to have some attributes that are node-specific,
some that are product-specific, or a combination. (More on this below.)
"""

# Create a 2-stage serial network.
network = serial_system(
	num_nodes=2,
	node_order_in_system=[2, 1],
	node_order_in_lists=[1, 2],
	local_holding_cost=[5, None],	# holding cost at node 2 will be product-specific, so leave it unspecified here
	stockout_cost=[20, 0],
	demand_type='UD',				# discrete uniform distribution, for easier debugging
	lo=1,
	hi=5,
	shipment_lead_time=[1, 2]
)

# Build a dict in which the keys are node indices and the values are the node objects,
# just to make it easier to access the nodes by index.
nodes = {n.index: n for n in network.nodes}

# Create 3 products, with indices 10, 20, and 30. Products 20 and 30 are both raw materials for product 10.
# To make 1 unit of product 10 requires 5 units of product 20 and 3 units of product 30.
# Make a dict in which the keys are product indices and the values are the product objects, for convenience.
products = {10: SupplyChainProduct(index=10), 20: SupplyChainProduct(index=20), 30: SupplyChainProduct(index=30)}
products[10].set_bill_of_materials(rm_index=20, num_needed=5)
products[10].set_bill_of_materials(rm_index=30, num_needed=3)

# Add the products to the nodes: node 1 (downstream) handles product 10, node 2 (upstream) handles 20 and 30.
nodes[1].add_product(products[10])
nodes[2].add_products([products[20], products[30]])

# Set some of the attributes of the products. Since node 1 only handles one product (product 10), by 
# setting the local_holding_cost, stockout_cost, and demand_source for node 1 when we called serial_system(),
# we effectively set those attributes for product 10.
products[20].local_holding_cost = 2
products[30].local_holding_cost = 3

# We can set attributes for product 10 directly in the SupplyChainProduct object; it's the same as setting
# it in the node, since node 1 only handles product 10.
products[10].inventory_policy = Policy(type='BS', base_stock_level=5, node=nodes[1], product=products[10])
# (The node= and product= arguments are somewhat annoying. I'm going to try to find a way to avoid that.)

# You can also set a node's attributes as a dict in which the keys are products and the values are
# the attribute values. This allows you to set (node, product)-specific values of the attribute.
nodes[2].inventory_policy = {
	20: Policy(type='BS', base_stock_level=15, node=nodes[2], product=products[20]),
	30: Policy(type='BS', base_stock_level=10, node=nodes[2], product=products[30])
}

# To access an attribute at a node/product, use SupplyChainNode.get_attribute(). This function will figure
# out where the attribute is set and return the appropriate value. It first looks to see whether
# the attribute is a dict at the node (meaning we have a (node, product)-specific value), then it looks
# to see whether the attribute is set at the product, and finally it looks to see whether it's set at the node.
print(nodes[1].get_attribute('local_holding_cost', product=10))		# = 5
print(nodes[1].get_attribute('shipment_lead_time', product=10))		# = 1
print(nodes[1].get_attribute('inventory_policy', product=10))		# = Policy(BS: base_stock_level=20.00)
print(nodes[2].get_attribute('local_holding_cost', product=30))		# = 3
print(nodes[2].get_attribute('inventory_policy', product=20))		# = Policy(BS: base_stock_level=10.00)
print(nodes[2].get_attribute('shipment_lead_time', product=20))		# = 2
print(nodes[2].get_attribute('shipment_lead_time', product=30))		# = 2

# You can get the BOM number for a given product/raw material pair:
print(products[10].get_bill_of_materials(rm_index=20))				# = 5
# You can get a list of all raw materials used by a product:
print(products[10].raw_material_indices)							# = [20, 30]
# or by a specific product at a specific node:
print(nodes[1].raw_material_indices_by_product(product_index=10))	# = [20, 30]
# You can also find out which predecessor nodes provide a specific raw material to a specific node:
print(nodes[1].raw_material_supplier_indices_by_product(product_index=10))	# = [2]

"""Every network has to have external supply. (Nodes can't just create a product with no
raw materials. This was true even pre-multi-product.) To specify that a node receives external supply,
you set that node's supply_type attribute to 'U' (for 'unlimited'). (This is kind of klugey and I
will probably come up with a better way in the future.) The serial_system() function automatically
sets supply_type = 'U' for the upstream-most node, which means that node 2 in our network has external supply.

The problem with this is that we haven't specified in the BOM that the products at node 2 require
raw materials from the external supplier. And I don't want to force the user to do that, since external
supply is really a sort of under-the-hood concept that I don't want the user to have to learn or interact with.

My solution to this was to create what I call the "network BOM" (NBOM), which assigns default BOM values to
certain pairs of nodes/products based on the structure of the network. The basic rule is: If node A is a 
predecessor to node B, and there are no BOM relationships specified between _any_ product at node A and _any_
product at node B, then _every_ product at node B is assumed to require 1 unit of _every_ product at node A as 
a raw material.

In the case of our network, that means that product 20 and product 30 require 1 unit of the item provided
by the external supplier. (That item is a "dummy" product assigned to the supplier. Dummy products always have
negative indices.) 

We don't set the NBOM explicitly -- we only set the BOM and the code automatically adds the network-based
relationships as needed. We can query the NBOM using SupplyChainNode.get_network_bill_of_materials(),
which returns the BOM relationship for a given (node, product) and a given (predecessor, RM). If the 
BOM is set explicitly, it returns that number, and if it's implicit from the network structure, it returns
that number. If there is no BOM relationship, it returns 0. 

If an NBOM relationship is implied by the network structure, the NBOM always equals 1. If you want it
to equal something else (e.g., if we wanted to say that you need 4 units of the external supplier product
to make 1 unit of product 30), you need to explicitly create a node that's a predecessor to node 2, 
create a product that's a raw material for product 30, and set the BOM explicitly.

The function SupplyChainNode.NBOM() is a shortcut to SupplyChainNode.get_network_bill_of_materials().
"""

# Get the NBOM for node 1, product 10 with node 2, product 20:
print(nodes[1].NBOM(product=10, predecessor=2, raw_material=20))		# = 5
# Get the NBOM for node 2, product 20 with the external supplier's dummy product:
print(nodes[2].NBOM(product=20, predecessor=None, raw_material=None))	# = 1

"""Every node has a raw material inventory for every product that it uses as a raw material inventory.
So, node 1 has RM inventory for products 20 and 30, and node 2 has RM inventory for the dummy product from
the external supplier. The RM inventories are by product _only_, not by (product, predecessor). 
Two implications of that:
	1. If a node has multiple suppliers that provide the same raw material, those supplies are pooled
		into a single raw material inventory.
	2. If a node has multiple products that use the same raw material, they share the same raw material
		inventory.
Item 2 is relevant for our network, because both product 20 and product 30 use the dummy product from the
external supplier as a raw material, so they both draw their raw materials from the same inventory.

OK, let's finally run the simulation.
"""

# Run simulation.
total_cost = simulation(network, 100, rand_seed=17, progress_bar=False, consistency_checks='E')

# Display results.
write_results(network=network, num_periods=100, columns_to_print=['basic', 'costs', 'RM', 'ITHC'])

"""Here are the first few rows of the results:

  t  | i=1      IO:EXT|10    OQ:2|20    OQ:2|30    IS:2|20    IS:2|30       RM:20    RM:30    OS:EXT|10       IL:10         HC         SC    ITHC    TC  | i=2      IO:1|20    IO:1|30    OQ:EXT|-5    IS:EXT|-5    RM:-5    OS:1|20    OS:1|30    IL:20    IL:30     HC    SC    ITHC     TC
---  -------  -----------  ---------  ---------  ---------  ---------  ----------  -------  -----------  ----------  ---------  ---------  ------  ----  -------  ---------  ---------  -----------  -----------  -------  ---------  ---------  -------  -------  -----  ----  ------  -----
  0  |                  2         10          6          0          0     0              0      2           3          15          0            0    15  |               10          6           16            0        0         10          6        5        4     22     0      38     60
  1  |                  2         10          6         10          6     0              0      2           3          15          0            0    15  |               10          6            4            0        0          5          4       -5       -2      0     0      22     22
  2  |                  1          5          3          5          4     0              1      1           3          18          0            0    18  |                5          3            5           16        0         10          0        6       -5     12     0      20     32
  3  |                  5         25         15         10          0     8.33333        0      3.33333    -1.66667    16.6667    33.3333       0    50  |               25         15           46            4        0         10          0      -15      -20      0     0      20     20
  4  |                  5         25         15         10          0    18.3333         0      0          -6.66667    36.6667   133.333        0   170  |               25         15            4            5        0          5          0      -35      -35      0     0      10     10
  5  |                  5         25         15          5          0    23.3333         0      0         -11.6667     46.6667   233.333        0   280  |               25         15           35           46        0         46          0      -14      -50      0     0      92     92
  6  |                  2         10          6         46          0    69.3333         0      0         -13.6667    138.667    273.333        0   412  |               10          6           27            4        0          4          0      -20      -56      0     0       8      8
  7  |                  2         10          6          4          0    73.3333         0      0         -15.6667    146.667    313.333        0   460  |               10          6           10           35        0         30          0        5      -62     10     0      60     70
  8  |                  2         10          6         30          0   103.333          0      0         -17.6667    206.667    353.333        0   560  |               10          6           41           27        0         10          0       22      -68     44     0      20     64
  9  |                  1          5          3         10          0   113.333          0      0         -18.6667    226.667    373.333        0   600  |                5          3           30           10        0          5          0       27      -71     54     0      10     64
 10  |                  3         15          9          5          0   118.333          0      0         -21.6667    236.667    433.333        0   670  |               15          9           19           41        0         15          0       53      -80    106     0      30    136
 
Here's how to decode the results:
	* Each node is represented by a group of columns. The node number is indicated in the first column in the group (i.e., i=1).
	* (node, product) pairs are indicated by a vertical line, so '2|20' means node 2, product 20.
	* 'EXT' means external supplier or customer.
	* State variable abbreviations are described here: https://stockpyl.readthedocs.io/en/latest/api/simulation/sim_io.html

So:
	* In period 0, we start with IL:10 = 5 at node 1, IL:20 = 15 and IL:30 = 10 at node 2. (By default, the initial IL equals
		the base-stock level.) These numbers aren't displayed in the table above, only the _ending_ ILs are.
	* Node 1 receives a demand of 2 for product 10 (IO:EXT|10 = 2). Its inventory position (IP) is now 5 - 2 = 3 and its
		base-stock level is 5, so it needs to order 2 units' worth of raw materials. Expressed in the units of the raw materials,
		that means it needs to order 10 of product 20 (because BOM = 5) and 6 of product 30 (because BOM = 3). In the table,
		OQ:2|20 = 10, OQ:2|30 = 6. 
	* Node 1 has sufficient inventory to fulfill the demand of 2, so it does (OS:EXT|10 = 2).
	* Node 1 ends the period with IL:10 = 3, and incurs a holding cost of 15 since the per-unit holding cost is 5. There is
		no stockout cost in this period, so we have HC = 15, SC = 0, TC = 15.
	* Node 2 receives an inbound order of 10 units for product 20 and 6 units for product 3 (IO:1|20 = 10, IO:1|30 = 6).
		Its inventory positions are now IP:20 = 15 - 10 = 5, IP:30 = 10 - 6 = 4 and its base-stock levels are 15 and 10, 
		respectively. So it needs to order 10 units of the external supplier dummy product for product 20, and another 6
		units of the external supplier dummy product for product 30. (Remember that the NBOM = 1 for these pairs.)
		So, OQ:EXT|-5 = 16. (-5 is the index of the dummy product at the external supplier.)
	* Node 2 has sufficient inventory to satisfy demand for both products, so it ships 10 units of product 20 and 6 units
		of product 30 (OS:1|20 = 10, OS:1|30 = 6).
	* Node 2 ends the period with IL:20 = 5, IL:30 = 4, so HC = 5 * 2 + 4 * 3 = 22, SC = 0. Node 2 also incurs the 
		in-transit holding cost for items that it shipped to node 1 that have not arrived yet; there are 10 units of
		product 20 and 6 units of product 30, and the holding cost rates are 2 and 3, so ITHC = 10 * 2 + 6 * 3 = 38;
		and TC = 22 + 38 = 60.
	* Jumping ahead to period 3, here's what's going on with the fractional quantities at node 1: 
		We start period 3 with 0 units of product 20 and 1 unit of product 30 in RM inventory (RM:20 = 0, RM:30 = 1 in period 2).
		We receive 10 units of product 20 and 0 of product 30 in period 3 (IS:2|20 = 10, IS:2|30 = 0 in period 3). So now we have
		10 units of product 20 and 1 of product 30, which is enough to make 1/3 unit of product 1 at node 1.
		This requires (1/3) * 5 = 1.6667 units of product 20 and (1/3) * 3 = 1 unit of product 30, so we end period 3 with
		RM:20 = 10 - 1.6667 = 8.3333 and RM:30 = 0 at node 1.   
"""

"""I would like you to double-check all 10 lines of the results above and make sure the logic seems right.
In particular, I feel like something is still wrong since we stop receiving product 30 at node 1 and therefore
stop satisfying demand entirely. I'm going to hunt for that bug and will update this file if I find it.

If you find any bugs, or just anything you can't explain/understand, post an issue at https://github.com/LarrySnyder/stockpyl/issues.
Describe the issue you're having, and include the code that generated your issue, if it's not the same code as above.

Once we are confident that this small instance is working correctly, I'd like you to create a slightly larger instance,
maybe 3 nodes/5 products, and perform the same kind of analysis to check it.
"""